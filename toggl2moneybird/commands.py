__all__ = ()

import keyring
import getpass
import webbrowser
from datetime import datetime, date, timedelta
from collections import defaultdict
from difflib import ndiff
from typing import DefaultDict

from .sync import EntrySync
from .menu import Menu
from .toggl import TogglTrack
from . import moneybird as mb

from rich.text import Text
from rich.table import Table
from rich.prompt import Confirm, Prompt
from rich.progress import Progress
from rich.live import Live
from rich.control import Control
from rich.console import Group, Console


back_months = 6
earliest_start_date = date(2023, 10, 1)


CURRENCY_SYMBOLS = dict(EUR='€', USD='$', GBP='£')


def get_currency_symbol(currency):
    return CURRENCY_SYMBOLS.get(currency, currency)


def format_currency(amount, currency=None):
    if currency:
        return f'{get_currency_symbol(currency)} {amount:,.2f}'
    else:
        return f'{amount:,.2f}'


def relaxed_date(year, month, day):
    if day > 28:
        days_in_month = (relaxed_date(year, month + 1, 1) - timedelta(days=1)).day
        if day > days_in_month:
            # Too many days for month, roll over
            month += 1
            day -= days_in_month

    while month < 1:
        month += 12
        year -= 1

    while month > 12:
        month -= 12
        year += 1

    return date(year, month, day)


def ask_hourly_rate_for(mb_project, default_currency=None):
    while True:
        ret = Prompt.ask(f"Hourly rate for project {mb_project.__rich__()}")
        ret = ret.strip()

        currency = default_currency

        for code, symbol in CURRENCY_SYMBOLS.items():
            if ret.startswith(symbol) or ret.endswith(symbol):
                currency = code
                ret = ret.strip(symbol)
                break
        else:
            if len(ret) > 4:
                if ret[0].isalpha() and ret[1].isalpha() and ret[2].isalpha() and not ret[3].isalpha():
                    currency = ret[:3].upper()
                    ret = ret[3:].strip()
                elif ret[-1].isalpha() and ret[-2].isalpha() and ret[-3].isalpha() and not ret[-4].isalpha():
                    currency = ret[-3:].upper()
                    ret = ret[:-3].strip()

        if ',' in ret and '.' not in ret:
            ret = ret.replace(',', '.')

        try:
            rate = float(ret)
        except ValueError:
            Console().print('[red]Please enter a valid currency amount[/red]')
            continue

        break

    while not currency:
        currency = Prompt.ask("In which currency? [magenta bold][EUR/USD/GBP/...][/magenta bold]")
        currency = currency.strip().upper()

        if len(currency) != 3:
            Console().print('[red]Please enter a valid 3-letter currency code[/red]')
            currency = None

    return rate, currency


def tt_login(console):
    tt = None

    logname = getpass.getuser()
    tt_api_token = keyring.get_password('name.rdb.toggl2moneybird.toggl-api-token', logname)
    if tt_api_token:
        tt = TogglTrack.login(tt_api_token)

    if not tt:
        with Live(None, console=console, auto_refresh=False, transient=True) as live:
            initial_header = ("", "   [plum3][bold]toggl[/bold]track[/plum3]", "")
            header = initial_header

            while not tt:
                live.update(Group(*header, "[bright_black]Email or API token: [/bright_black]"), refresh=True)

                console.print(Control.show_cursor(True))
                email = input()
                console.print(Control.show_cursor(False), Control.move(0, -1))

                if '@' not in email and len(email) == 32:
                    password = 'api_token'
                else:
                    live.update(Group(*header, "[bright_black]Email or API token:[/bright_black] " + email, "[bright_black]          Password: [/bright_black]"), refresh=True)

                    console.print(Control.show_cursor(True))
                    password = getpass.getpass("")
                    console.print(Control.show_cursor(False), Control.move(0, -1))

                tt = TogglTrack.login(email, password)
                if not tt:
                    header = initial_header + ("[red bold]Invalid credentials[/red bold], try again:",)

    console.print(f"Logged into [plum3][bold]toggl[/bold]track[/plum3] as [bold yellow]{tt.fullname}[/bold yellow]")

    keyring.set_password('name.rdb.toggl2moneybird.toggl-api-token', logname, tt.api_token)
    return tt


def tt_logout(console):
    logname = getpass.getuser()
    keyring.delete_password('name.rdb.toggl2moneybird.toggl-api-token', logname)


def mb_entry_data_table(entries_data, mb_admin, **kwargs):
    table = Table(**kwargs)
    table.add_column("date", justify="right", style="green", no_wrap=True)
    table.add_column("time", justify="left", style="yellow", no_wrap=True)
    table.add_column("hrs", style="magenta")
    table.add_column("project", style="blue bold")
    table.add_column("description", justify="left")

    for entry, data in entries_data:
        if entry:
            dur = entry.duration / 3600
            paused_dur = entry.paused_duration
            date, time = entry.started_at.isoformat().split('T', 1)
        else:
            dur = 0
            paused_dur = 0

        dur_str = '%.1fh' % (dur)
        new_dur_str = dur_str
        if data is not None and 'started_at' in data and 'ended_at' in data:
            start = datetime.fromisoformat(data['started_at'][:16])
            end = datetime.fromisoformat(data['ended_at'][:16])
            date, time = data.get('started_at').split('T', 1)
            dur = int((end - start).total_seconds())
            dur -= data.get('paused_duration', paused_dur)
            dur /= 3600
            new_dur_str = '%.1fh' % (dur)

        if not entry:
            dur_str = new_dur_str
        elif new_dur_str != dur_str:
            dur_str = f'[strike]{dur_str}[/strike] {new_dur_str}'

        if data is not None and data.get('project_id'):
            project = mb_admin.get_project(data['project_id'])
            project_name = project.__rich__()
        else:
            project = None
            project_name = ''

        if not entry:
            desc = data['description']
        elif data:
            desc = data.get('description')
            if desc is None and entry.description:
                desc = entry.description
            elif desc is not None and entry.description and desc != entry.description:
                strike_on = False
                new_desc = ''
                for word in ndiff(entry.description.split(' '), desc.split(' ')):
                    if word[0] == '?':
                        continue
                    elif word[0] == '-':
                        if not strike_on:
                            new_desc += '[strike bright_black]'
                            strike_on = True
                    elif strike_on:
                        if new_desc.endswith(' '):
                            new_desc = new_desc[:-1] + '[/strike bright_black] '
                        else:
                            new_desc += '[/strike bright_black]'
                        strike_on = False

                    if word[0] == '+':
                        new_desc += f'[bold]{word[2:]}[/bold] '
                    else:
                        new_desc += word[2:] + ' '

                desc = new_desc.rstrip()
                if strike_on:
                    desc += '[/strike bright_black]'

            if entry.project:
                if not project:
                    project_name = entry.project.__rich__()
                elif entry.project != project:
                    project_name = f'[strike]{entry.project.__rich__()}[/strike] {project_name}'
        else:
            desc = entry.description
            project_name = entry.project.name if entry.project else ''

        if data and data.get('billable'):
            if desc:
                desc = '💰 ' + desc
            else:
                desc = '💰'

        if entry and not data:
            table.add_row(date, time[:5], dur_str, project_name, desc, style='strike bright_black')
        else:
            table.add_row(date, time[:5], dur_str, project_name, desc)

    return table


def do_mutations(console, args, mb_admin, mutations):
    num_create = 0
    num_update = 0
    num_delete = 0
    num_locked = 0
    orig_mutations = mutations
    mutations = []
    for mb_entry, data in orig_mutations:
        if mb_entry and mb_entry.detail is not None:
            num_locked += 1
            continue

        mutations.append((mb_entry, data))

        if not mb_entry:
            num_create += 1
        elif data is not None:
            num_update += 1
        else:
            num_delete += 1

    if num_locked:
        console.print("[bold red]WARNING![/bold red]", num_locked, "entries cannot be modified because they were already invoiced.")

    if not mutations:
        console.print("Nothing to do!")
        return True

    line = []
    if num_create:
        line += [num_create, "entry" if num_create == 1 else "entries", "to be created"]

    if num_update:
        if line:
            line[-1] += ","
            line += [num_update, "to be updated"]
        else:
            line += [num_update, "entry" if num_update == 1 else "entries", "to be updated"]

    if num_delete:
        if line:
            line[-1] += ","
            line += [num_delete, "to be [bold red]DELETED[/bold red]"]
        else:
            line += [num_delete, "entry" if num_delete == 1 else "entries", "to be [bold red]DELETED[/bold red]"]

    line[-1] += ":"
    console.print(*line)

    console.print(mb_entry_data_table(mutations, mb_admin))

    if not args.yes and not Confirm.ask("Does this look good?"):
        console.print("Aborting.")
        return False

    with Progress(console=console, transient=True) as progress:
        task_id = progress.add_task("[yellow]Updating...", total=len(mutations))

        for mb_entry, data in mutations:
            if not mb_entry:
                if args.dry_run:
                    console.print("Would have inserted new entry")
                    progress.advance(task_id)
                else:
                    id = mb_admin.create_time_entry(data, progress=progress, task_id=task_id)['id']
                    console.print("Inserted", id)

            elif data is not None:
                id = mb_entry.id
                if args.dry_run:
                    console.print("Would have updated", id)
                    progress.advance(task_id)
                else:
                    mb_admin.update_time_entry(id, data, progress=progress, task_id=task_id)
                    console.print("Updated", id)

            else:
                id = mb_entry.id
                if args.dry_run:
                    console.print("Would have deleted", id)
                    progress.advance(task_id)
                else:
                    mb_admin.delete_time_entry(id, progress=progress, task_id=task_id)
                    console.print("Deleted", id)

    console.print("Synchronized successfully.")
    console.print()
    return True


def cmd_sync(console, args, mb_admin):
    today = date.today()
    if back_months < 3:
        start_date = relaxed_date(today.year, today.month - back_months, 1)
    else:
        # Limit of the Toggl Track API
        start_date = relaxed_date(today.year, today.month - 3, today.day)

    if start_date < earliest_start_date:
        start_date = earliest_start_date

    end_date = relaxed_date(today.year, today.month + 1, 1)

    console.print(Text.assemble("Synchronizing time entries from ", (start_date.isoformat(), "bold green"), " to ", (end_date.isoformat(), "bold magenta")))

    tt = tt_login(console)
    tt_entries = tt.get_time_entries(start_date, end_date)
    tt_entries.sort(key=lambda e: e['start'])

    exclude_tags = frozenset(args.exclude_tags or ())

    sync = EntrySync()
    for tt_entry in tt_entries:
        if exclude_tags.intersection(tt_entry['tags']):
            continue

        tt_project = tt.get_project(tt_entry['project_id'])
        if not args.projects or tt_project['name'] in args.projects:
            if args.unbillable_tag:
                tt_entry['billable'] = args.unbillable_tag not in tt_entry['tags']
            if args.only_billable and not tt_entry['billable']:
                continue
            sync.add_tt_entry(tt_entry, tt_project)

    with Progress(console=console, transient=True) as progress:
        mb_entries = mb_admin.get_time_entries(start_date, end_date, progress=progress)
        mb_users = mb_admin.get_users(progress=progress)

    if len(mb_users) == 1:
        mb_user = mb_users[0]
        console.print("Log time as user:", mb_user)
    else:
        mb_user = Menu.ask("Log time as user", mb_users)

    sync.link(mb_entries)

    if sync.has_missing_projects(args.only_billable):
        mb_projects = mb_admin.get_projects()

        if args.projects:
            mb_projects = [mb_project for mb_project in mb_projects if mb_project.name in args.projects]

        for tt_project in sync.map_projects_by_name(mb_projects):
            if Confirm.ask(f"Add missing project [bold blue]{tt_project['name']}[/bold blue]?"):
                mb_project = mb_admin.create_project(tt_project['name'])
                sync.map_project(tt_project['id'], mb_project)

    for mb_project in sync.get_projects_without_contacts(args.only_billable):
        if args.projects and mb_project.name not in args.projects:
            continue

        mb_contact = Menu.ask(f"Bill project {mb_project.__rich__()} to", mb_admin.get_contacts())
        if mb_contact:
            sync.set_project_contact(mb_project, mb_contact)

    mutations = sync.get_mutations(mb_user)
    do_mutations(console, args, mb_admin, mutations)

    if not mutations and args.only_billable and sync.has_missing_projects(False):
        console.print("To include unbillable entries, add the [bold]--include-unbillable[/bold] flag.")


def cmd_invoice(console, args, mb_admin):
    today = date.today()
    start_date = relaxed_date(today.year, today.month - back_months, 1)

    # Toggl Track has a limit on the earliest start date
    if back_months < 3:
        tt_start_date = start_date
    else:
        tt_start_date = relaxed_date(today.year, today.month - 3, today.day)

    if start_date < earliest_start_date:
        start_date = earliest_start_date

    end_date = relaxed_date(today.year, today.month + 1, 1)

    with Progress(console=console, transient=True) as progress:
        entries = mb_admin.get_time_entries(start_date, end_date, progress=progress)

    tt = tt_login(console)
    tt_entries = tt.get_time_entries(tt_start_date, end_date)
    tt_entries.sort(key=lambda e: e['start'])

    exclude_tags = frozenset(args.exclude_tags or ())

    sync = EntrySync()
    for tt_entry in tt_entries:
        if exclude_tags.intersection(tt_entry['tags']):
            continue

        tt_project = tt.get_project(tt_entry['project_id'])
        if not args.projects or tt_project['name'] in args.projects:
            if args.unbillable_tag:
                tt_entry['billable'] = args.unbillable_tag not in tt_entry['tags']
            if args.only_billable and not tt_entry['billable']:
                continue
            sync.add_tt_entry(tt_entry, tt_project)

    sync.link(entries)

    mb_projects = mb_admin.get_projects()
    if args.projects:
        mb_projects = [mb_project for mb_project in mb_projects if mb_project.name in args.projects]

    if sync.has_missing_projects(args.only_billable):
        sync.map_projects_by_name(mb_projects)

    mutations = sync.get_mutations(mb_admin.get_users()[0])

    # Filter out mutations before tt_start_date, and already invoiced entries
    mutations = [(mb_entry, diff) for mb_entry, diff in mutations if not mb_entry or (mb_entry.started_at.date() >= tt_start_date and not mb_entry.detail)]

    if len(mutations) > 0 and Confirm.ask(f"{len(mutations)} entries are out of sync. Sync first?"):
        if not do_mutations(console, args, mb_admin, mutations):
            return

    with Progress(console=console, transient=True) as progress:
        entries = mb_admin.get_time_entries(state='open', progress=progress)

    if args.projects:
        entries = entries.filter(lambda entry: entry.project and entry.project.name in args.projects)

    by_cc = defaultdict(lambda: ([], [], mb.TimeEntries()))
    if entries:
        entries.sort()

        mb_projects_by_name = {}
        for mb_project in mb_projects:
            mb_projects_by_name[mb_project.name.lower()] = mb_project

        rate_by_project = {}
        currency_by_project = {}
        for tt_project in tt.get_projects():
            mb_project = sync.get_project_by_tt_id(tt_project['id'])
            if not mb_project:
                mb_project = mb_projects_by_name.get(tt_project['name'].lower())
                if not mb_project:
                    continue

            rate = args.rate or tt_project['rate']
            currency = args.currency or tt_project['currency']

            # Use default hourly rate / currency of workspace
            if rate is None or currency is None:
                tt_workspace = tt.get_workspace(tt_project['workspace_id'])
                rate = rate or tt_workspace['default_hourly_rate']
                currency = currency or tt_workspace['default_currency']

            rate_by_project[mb_project] = rate
            currency_by_project[mb_project] = currency

        seen_projects = set()
        unbilled: DefaultDict[tuple, DefaultDict[mb.Project, float]] = \
            defaultdict(lambda: defaultdict(float))
        for entry in entries:
            mb_project = entry.project
            if mb_project:
                if mb_project not in currency_by_project:
                    console.print(f"Couldn't find corresponding project for {mb_project.__rich__()} in Toggl Track. Do a sync first?")
                    return

                rate = rate_by_project[mb_project]
                currency = currency_by_project[mb_project]
                if rate is None or currency is None:
                    rate, currency = ask_hourly_rate_for(mb_project)
                    rate_by_project[mb_project] = rate
                    currency_by_project[mb_project] = currency

                period = entry.started_at.strftime('%Y-%m')
                unbilled[(period, entry.contact, currency)][mb_project] += entry.duration

                if mb_project not in seen_projects:
                    symbol = get_currency_symbol(currency)
                    console.print(f'Charging [yellow bold]{symbol}[/yellow bold] {rate:.2f}/hr for project {mb_project.__rich__()}')
                    seen_projects.add(mb_project)

        menu = Menu(prompt="Choose a contact and period from the list below.", show_edge=False)
        menu.add_column("period", justify="right", style="green", no_wrap=True)
        menu.add_column("hrs", style="magenta")
        menu.add_column("total", style="yellow")
        menu.add_column("contact", style="cyan")
        menu.add_column("project(s)", style="blue")

        unbilled_items = list(unbilled.items())
        for (period, contact, currency), proj_durations in unbilled_items:
            symbol = get_currency_symbol(currency)
            duration = 0.0
            total = 0.0
            project_strs = []
            for project, proj_duration in proj_durations.items():
                duration += proj_duration
                rate = rate_by_project[project]
                total += rate * proj_duration / 3600
                project_strs.append(project.__rich__())

            amount = round(duration / 3600, 1)
            menu.add_row(period, f"{amount:.1f}h", f"{symbol} {total:.2f}", contact.__rich__(), ', '.join(project_strs), value=(period, contact, currency, list(proj_durations.keys())))

        for period, contact, currency, projects in menu.choose(multiple=True):
            period_entries = entries.filter(contact=contact, project=projects,
                                            func=lambda entry: entry.started_at.isoformat().startswith(period + '-'))
            cc = (contact, currency)
            by_cc[cc][0].append(period)
            by_cc[cc][1].extend(projects)
            by_cc[cc][2].extend(period_entries)

        del period, contact, currency, projects
    else:
        console.print("No unbilled hours found.")

    if len(by_cc) > 1:
        console.print(f"Multiple contacts or currencies selected, creating {len(by_cc)} invoices.")

    for (contact, currency), (periods, projects, entries) in by_cc.items():
        period_str = f"[green]{'[/green], [green]'.join(periods)}[/green]"
        console.print(f"Time entries for contact {contact.__rich__()} during {period_str} in [yellow bold]{currency}[/yellow bold]")
        console.print(entries)
        if not args.yes and not Confirm.ask("Create a draft invoice for these time entries?"):
            return

        # Check for the previously used ledger account and tax rate for this
        # project
        prev_ledger_accounts = set()
        prev_tax_rates = set()
        for invoice in mb_admin.get_sales_invoices(contact=contact):
            for detail in invoice.details:
                if detail.project in projects and detail.period:
                    if detail.ledger_account:
                        prev_ledger_accounts.add(detail.ledger_account)
                    if detail.tax_rate:
                        prev_tax_rates.add(detail.tax_rate)

        default_ledger_account = None
        if len(prev_ledger_accounts) == 1:
            default_ledger_account, = prev_ledger_accounts

        default_tax_rate = None
        if len(prev_tax_rates) == 1:
            default_tax_rate, = prev_tax_rates

        ledger_account = Menu.ask("Ledger account", mb_admin.get_ledger_accounts(document_type="sales_invoice"), default=default_ledger_account)
        tax_rate = Menu.ask("Tax rate", mb_admin.get_tax_rates(tax_rate_type="sales_invoice"), default=default_tax_rate)

        data = {
            'contact_id': contact.id,
            'currency': currency,
            'prices_are_incl_tax': False,
            'details_attributes': [],
        }

        table = Table(show_edge=False, title=f"Invoice for contact {contact.__rich__()} during {period_str} in [yellow bold]{currency}[/yellow bold]")
        table.add_column("", justify="right", style="magenta", no_wrap=True)
        table.add_column("Description")
        table.add_column("Price")
        table.add_column("Total", style="yellow")
        if tax_rate.show_tax:
            table.add_column("VAT")

        subtotal = 0.0
        for entry in entries:
            rate = rate_by_project[entry.project]
            attrs = {
                'price': rate,
                'amount': f'{entry.duration / 3600:.1f}h',
                'period': f'{entry.started_at:%Y%m%d}..{entry.ended_at:%Y%m%d}',
                'description': entry.description,
                'project_id': entry.project.id if entry.project else None,
                'time_entry_ids': [entry.id],
                'ledger_account_id': ledger_account.id if ledger_account else None,
                'tax_rate_id': tax_rate.id if tax_rate else None,
            }
            data['details_attributes'].append(attrs)

            desc = f'{entry.description}\n[bright_black]Date:[/bright_black] [green]{entry.started_at:%B %d, %Y}[/green]'

            total = rate * round(entry.duration / 3600, 1)
            subtotal += total
            cells = [attrs['amount'], desc, '[green]' + format_currency(rate, currency), format_currency(total, currency)]
            if tax_rate.show_tax:
                cells.append(f'[cyan]{float(tax_rate.percentage):g}[/cyan]%')
            table.add_row(*cells)

        table.add_section()
        if tax_rate.show_tax:
            vat = round(subtotal * float(tax_rate.percentage) / 100, 2)
            total = subtotal + vat
            table.add_row('', '', '[bold]Subtotal', format_currency(subtotal, currency))
            table.add_row('', '', f'[cyan]{float(tax_rate.percentage):g}[/cyan]% VAT', format_currency(vat, currency))
            table.add_section()
        else:
            total = subtotal

        table.add_row('', '', '[bold]Total', format_currency(total, currency))

        console.print()
        console.print(table)
        console.print()
        if not args.yes and not Confirm.ask("Does this look good?"):
            console.print("Aborting.")
            return

        if args.dry_run:
            console.print("Not submitting invoice in dry-run mode.")
        else:
            obj = mb_admin.create_sales_invoice(data)
            console.print(f"Created invoice [bright_black]Draft #{obj['draft_id']}[/bright_black], opening in web browser.")
            webbrowser.open(f"https://moneybird.com/{mb_admin.id}/sales_invoices/{obj['id']}")

    invoices = []
    for invoice in mb_admin.get_sales_invoices(state='draft'):
        for detail in invoice.details:
            if detail.project and detail.period:
                break
        else:
            continue

        invoices.append(invoice)

    if invoices:
        console.print("The following invoices are currently waiting to be sent:")

        table = Table()
        table.add_column("", style="bright_black", no_wrap=True)
        table.add_column("period", style="green", no_wrap=True)
        table.add_column("total", style="yellow", no_wrap=True)
        table.add_column("contact", style="cyan")
        table.add_column("project(s)", style="blue")

        for invoice in invoices:
            contact = invoice.contact
            symbol = get_currency_symbol(invoice.currency)
            projects = set()
            first_start_date = None
            last_end_date = None
            for detail in invoice.details:
                if detail.project:
                    projects.add(detail.project)
                if detail.period:
                    start_date, end_date = mb.parse_period(detail.period)
                    if first_start_date is None or start_date < first_start_date:
                        first_start_date = start_date
                    if last_end_date is None or end_date > last_end_date:
                        last_end_date = end_date

            if first_start_date is None or last_end_date is None:
                # Shouldn't happen, but shut up type checker
                continue

            if first_start_date.year == last_end_date.year:
                if first_start_date.month == last_end_date.month:
                    if first_start_date.day == last_end_date.day:
                        period = first_start_date.isoformat()
                    else:
                        period = first_start_date.isoformat()[:7]
                elif (first_start_date.month - 1) // 3 == (last_end_date.month - 1) // 3:
                    quarter = (first_start_date.month - 1) // 3 + 1
                    period = f'{first_start_date.year} Q{quarter}'
                elif first_start_date.month == last_end_date.month - 1:
                    period = f'{first_start_date.year}-{first_start_date.month:0>2}/{last_end_date.month}'
                else:
                    period = 'Multiple'
            else:
                period = 'Multiple'

            project_str = ', '.join([project.__rich__() for project in projects])
            table.add_row(f'Draft #{invoice.draft_id}', period, f"{symbol} {invoice.total_price_excl_tax}", contact.__rich__(), project_str)

        console.print(table)


def cmd_erase(console, args, mb_admin):
    with Progress(console=console, transient=True) as progress:
        mb_entries = mb_admin.get_time_entries(progress=progress)

    if args.projects:
        mb_entries = mb_entries.filter(lambda mb_entry: mb_entry.project and mb_entry.project.name in args.projects)

    if not mb_entries:
        console.print("No entries to erase.")
        return

    console.print(mb_entries)

    if args.yes or Confirm.ask("Erase ALL above entries?"):
        with Progress(console=console, transient=True) as progress:
            task_id = progress.add_task("[red]Deleting...", total=len(mb_entries))

            for mb_entry in mb_entries:
                id = mb_entry.id
                if args.dry_run:
                    console.print("Would have deleted", id)
                    progress.advance(task_id)
                else:
                    mb_admin.delete_time_entry(id, progress=progress, task_id=task_id)
                    console.print("Deleted", id)

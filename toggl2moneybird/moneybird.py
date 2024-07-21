__all__ = ()

from datetime import date, datetime
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser
import json
import collections.abc
from typing import Optional, Sequence, cast

from rich.table import Table
from rich.pretty import pprint


CLIENT_ID = 'd5163471757eec41abf327e25669d084'
CLIENT_SECRET = '741d28507936721d3c612dd99dc6bdf3830da210b44932c798f5b4ef1b7faa2f'
LOCALHOST_PORT = 28510
API_SCOPES = 'sales_invoices', 'time_entries', 'settings'
CHUNK_SIZE = 1024


def normalize(name):
    return name.strip().replace('.', '').replace('  ', ' ').lower()


def parse_timestamp(str):
    str = str.replace(' UTC', '+00:00')
    str = str.replace('Z', '+00:00')
    return datetime.fromisoformat(str)


def parse_period(str):
    begin, end = str.split('..', 1)
    begin_date = date.fromisoformat(f'{begin[:4]}-{begin[4:6]}-{begin[6:8]}')
    end_date = date.fromisoformat(f'{end[:4]}-{end[4:6]}-{end[6:8]}')
    return (begin_date, end_date)


def entry_duration(entry):
    start = parse_timestamp(entry['started_at'][0:16])
    end = parse_timestamp(entry['ended_at'][0:16])
    dur = int((end - start).total_seconds())
    dur -= entry.get('paused_duration', 0)
    return dur


def entry_diff(old, new):
    diff = {}
    for key, new_value in new.items():
        old_value = old.get(key)
        if old_value == new_value:
            continue

        cmp_old_value = str(old_value)
        cmp_new_value = str(new_value)
        if key.endswith('_at'):
            cmp_old_value = cmp_old_value[:16]
            cmp_new_value = cmp_new_value[:16]

        if cmp_old_value != cmp_new_value:
            diff[key] = new_value

    return diff


def contact_name(contact):
    name = contact.get('company_name')
    if name:
        return '🏢 ' + name
    else:
        return f"🧍 {contact['firstname']} {contact['lastname']}"


class APIError(Exception):
    def __init__(self, code):
        self.code = code


class APIObject:
    id: int

    def __init__(self, data):
        self.id = int(data['id'])
        self.__data = data

    def get_data_diff(self, data):
        cur_data = self.__data
        diff = {}
        for key, new_value in data.items():
            cur_value = cur_data.get(key)
            if cur_value != new_value:
                diff[key] = new_value

        return diff

    def __getattr__(self, attr):
        if attr not in self.__data:
            raise AttributeError
        return self.__data[attr]

    def __hash__(self):
        return self.id

    def __eq__(self, other):
        return isinstance(other, APIObject) and self.id == other.id

    def __lt__(self, other):
        return self.id < other.id


class User(APIObject):
    def __rich__(self):
        return f'[bold yellow]{self.name}[/bold yellow]'

    def matches(self, q):
        return ' ' + normalize(q) in ' ' + normalize(self.name)


class Project(APIObject):
    def __rich__(self):
        return f'[bold blue]{self.name}[/bold blue]'

    def matches(self, q):
        return ' ' + normalize(q) in ' ' + normalize(self.name)


class Contact(APIObject):
    def __rich__(self):
        name = self.company_name
        if name:
            return f'[bold cyan]🏢 {name}[/bold cyan]'
        else:
            return f'[bold cyan]🧍 {self.firstname} {self.lastname}[/bold cyan]'

    def matches(self, q):
        if self.company_name:
            return ' ' + normalize(q) in ' ' + normalize(self.company_name)
        else:
            return ' ' + normalize(q) in ' ' + normalize(self.firstname + ' ' + self.lastname) \
                or ' ' + normalize(q) in ' ' + normalize(self.lastname + ' ' + self.firstname)


class LedgerAccount(APIObject):
    def __rich__(self):
        return f'[bold]{self.name}[/bold]'

    def matches(self, q):
        return ' ' + normalize(q) in ' ' + normalize(self.name)


class TaxRate(APIObject):
    def __rich__(self):
        return f'[bold]{self.name}[/bold]'

    def matches(self, q):
        return ' ' + normalize(q) in ' ' + normalize(self.name)


class SalesInvoice(APIObject):
    class Detail(APIObject):
        project: Optional[Project]
        tax_rate: Optional[TaxRate]
        ledger_account: Optional[LedgerAccount]
        description: str

        def __init__(self, data):
            APIObject.__init__(self, data)
            self.project = None
            self.tax_rate = None
            self.ledger_account = None

    contact: Optional[Contact]
    details: Sequence[Detail]

    def __rich__(self):
        if self.draft_id:
            return f'[bold bright_black]Draft #{self.invoice_id}[/bold bright_black]'
        else:
            return f'[bold]#{self.invoice_id}[/bold]'

    def matches(self, q):
        return ' ' + normalize(q) in ' ' + normalize(self.invoice_id)


class TimeEntry(APIObject):
    started_at: datetime
    ended_at: datetime
    paused_duration: int
    user: Optional[User]
    contact: Optional[Contact]
    project: Optional[Project]

    def __init__(self, data):
        APIObject.__init__(self, data)
        self.user = None
        self.contact = None
        self.project = None

    @property
    def duration(self):
        dur = int((self.ended_at - self.started_at).total_seconds())
        dur -= self.paused_duration
        return dur

    def __lt__(self, other):
        if self.started_at != other.started_at:
            return self.started_at < other.started_at

        return self.id < other.id


class TimeEntries(list):
    def filter(self, func=None, *, contact=None, project=None):
        return TimeEntries([entry for entry in self if (func is None or func(entry)) and (contact is None or entry.contact == contact) and (project is None or entry.project == project or (isinstance(project, collections.abc.Container) and entry.project in project))])

    def __rich__(self):
        table = Table()
        table.add_column("date", justify="right", style="green", no_wrap=True)
        table.add_column("time", justify="left", style=f"yellow", no_wrap=True)
        table.add_column("hrs", style="magenta")
        table.add_column("project", style="bold blue")
        table.add_column("description", justify="left")

        for entry in self:
            dur = entry.duration / 3600
            date, time = entry.started_at.isoformat().split('T', 1)
            time = time[:5]
            project_name = entry.project.name if entry.project else ''
            table.add_row(date, time, '%.1fh' % (dur), project_name, entry.description)

        return table


class _OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if '?' in self.path:
            server = cast(_OAuthServer, self.server)

            for part in self.path.split('?', 1)[-1].split('&'):
                if part.startswith('code='):
                    server.oauth_code = part[5:]
                elif part.startswith('error='):
                    server.oauth_error = part[6:]

        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"<p>Request processed. You may now close this window.</p><script>window.close();</script>")


class _OAuthServer(HTTPServer):
    def __init__(self):
        HTTPServer.__init__(self, ('localhost', LOCALHOST_PORT), _OAuthHandler)
        self.oauth_error = None
        self.oauth_code = None


class Administration:
    def __init__(self, data, headers):
        self.id = data['id']
        self.name = data['name']
        self.currency = data['currency']

        self.__headers = headers

        self.__cache: dict[str, dict] = {
            'projects': {},
            'contacts': {},
            'users': {},
            'ledger_accounts': {},
            'tax_rates': {},
        }
        self.__caches_complete = set()

    def __rich__(self):
        return "[bold blue]" + self.name

    def _request(self, method, path, data=None, *,
                 filters=(), per_page=100, progress=None, task_id=None):
        if '?' in path:
            path = path.replace('?', '.json?', 1)
        else:
            path += '.json'

        params = None
        if method == 'GET':
            params = {'per_page': str(per_page)}

            if filters:
                params['filter'] = ','.join(filters)

        url = f'https://moneybird.com/api/v2/{self.id}/{path}'
        r = requests.request(method, url, params=params, headers=self.__headers, json=data, stream=progress is not None)

        total_pages = 1
        next_url = None
        if method == 'GET' and r.status_code == 200:
            next_url = r.links.get('next', {}).get('url')
            if next_url:
                # It's OK if we end up reading more pages than this
                total_count = r.headers.get('x-total-count')
                if total_count:
                    total_pages = -(-int(total_count) // per_page)
                    total_pages = max(2, total_pages)

        advance = (1 / total_pages) if progress else 0
        data = self.__read_data(r, progress, task_id, advance)

        if r.status_code >= 300:
            print(f"{method} {url}")
            pprint(r)
            pprint(data)
            raise APIError(r.status_code)

        read_pages = 1
        while next_url:
            r = requests.get(next_url, headers=self.__headers, stream=progress is not None)
            page_data = self.__read_data(r, progress, task_id, advance)

            read_pages += 1
            if read_pages >= total_pages:
                # We got to the expected number of pages, stop advancing.
                advance = 0

            if r.status_code >= 300:
                print(f"GET {next_url}")
                pprint(r)
                pprint(page_data)
                raise APIError(r.status_code)

            data += page_data
            next_url = r.links.get('next', {}).get('url')

        if read_pages < total_pages and progress:
            progress.advance(task_id, advance=advance * (total_pages - read_pages))

        return data

    def __read_data(self, r, progress, task_id, advance):
        if progress and advance:
            # Stream.
            if 'content-length' in r.headers:
                page_bytes = int(r.headers['content-length'])
            else:
                page_bytes = None

            data = b''
            advanced = 0
            for chunk in r.iter_content(CHUNK_SIZE):
                data += chunk

                if page_bytes is not None:
                    chunk_advance = advance * len(chunk) / page_bytes
                    if advanced + chunk_advance > advance:
                        # Don't advance too much if we read more than expected.
                        chunk_advance = advance - advanced

                    progress.advance(task_id, advance=chunk_advance)
                    advanced += chunk_advance

            if advanced < advance:
                # We read less than expected, adjust progress.
                progress.advance(task_id, advance=advance - advanced)
        else:
            # Fetch in one go.
            data = r.content

        if r.status_code == 204:
            return None
        elif r.headers.get('content-type') == 'application/json':
            return json.loads(data)
        else:
            return data

    def __refresh_cache(self, noun: str, type, *, progress=None):
        cache = self.__cache[noun]

        if progress:
            task_id = progress.add_task(f"Fetching {noun.replace('_', ' ')}...", total=1)
        else:
            task_id = None

        for data in self._request('GET', noun, progress=progress, task_id=task_id):
            cache[int(data['id'])] = type(data)

        self.__caches_complete.add(noun)
        return cache

    def __get_cached_all(self, noun: str, type, *, progress=None):
        if noun not in self.__caches_complete:
            self.__refresh_cache(noun, type, progress=progress)

        return self.__cache[noun].values()

    def __get_cached_one(self, noun: str, type, id: int):
        id = int(id)
        cache = self.__cache[noun]
        obj = cache.get(id)
        if obj:
            return obj

        # Didn't have a complete cache?
        if not self.__caches_complete:
            self.__refresh_cache(noun, type)
            obj = cache.get(id)
            if obj:
                return obj
        else:
            # May have been added in the meantime.
            data = self._request('GET', f'{noun}/{id}')
            obj = type(data)
            cache[obj.id] = obj
            return obj

        raise APIError(404)

    def __post_and_cache(self, noun: str, type, body: dict, **kwargs):
        data = self._request('POST', noun, body, **kwargs)
        obj = type(data)
        self.__cache[noun][obj.id] = obj
        return obj

    def get_contact(self, id: int) -> Contact:
        return self.__get_cached_one('contacts', Contact, id)

    def get_contacts(self, *, progress=None) -> Sequence[Contact]:
        return list(self.__get_cached_all('contacts', Contact, progress=progress))

    def create_contact(self, data, **kwargs) -> Contact:
        return self.__post_and_cache('contacts', Contact, {'contact': data}, **kwargs)

    def get_user(self, id: int) -> User:
        return self.__get_cached_one('users', User, id)

    def get_users(self, *, progress=None) -> Sequence[User]:
        return list(self.__get_cached_all('users', User, progress=progress))

    def get_project(self, id: int) -> Project:
        return self.__get_cached_one('projects', Project, id)

    def get_projects(self, *, progress=None) -> Sequence[Project]:
        return list(self.__get_cached_all('projects', Project, progress=progress))

    def create_project(self, name, **kwargs) -> Project:
        return self.__post_and_cache('projects', Project, {'project': {'name': name}}, **kwargs)

    def get_ledger_account(self, id: int) -> LedgerAccount:
        return self.__get_cached_one('ledger_accounts', LedgerAccount, id)

    def get_ledger_accounts(self, *, document_type=None, progress=None) -> Sequence[LedgerAccount]:
        accounts = self.__get_cached_all('ledger_accounts', LedgerAccount, progress=progress)
        if document_type:
            return [account for account in accounts if document_type in account.allowed_document_types]
        else:
            return list(accounts)

    def get_tax_rate(self, id: int) -> TaxRate:
        # Has no individual getter
        if 'tax_rates' not in self.__caches_complete:
            self.__refresh_cache('tax_rates', TaxRate)

        return self.__cache['tax_rates'][id]

    def get_tax_rates(self, *, tax_rate_type=None, progress=None) -> Sequence[TaxRate]:
        rates = self.__get_cached_all('tax_rates', TaxRate, progress=progress)
        if tax_rate_type:
            return [rate for rate in rates if tax_rate_type == rate.tax_rate_type]
        else:
            return list(rates)

    def get_time_entries(self, start_date=None, end_date=None, *, contact=None, project=None, user=None, state=None, progress=None) -> TimeEntries:
        filters = []
        if start_date or end_date:
            filters.append(f'period:{start_date:%Y%m%d}..{end_date:%Y%m%d}')

        if state:
            filters.append(f'state:{state}')

        if contact:
            filters.append(f'contact_id:{contact.id}')

        if project:
            filters.append(f'project_id:{project.id}')

        if user:
            filters.append(f'user_id:{user.id}')

        if progress:
            task_id = progress.add_task('Fetching time entries...', total=1)
        else:
            task_id = None

        path = 'time_entries'
        data = self._request('GET', path, filters=filters, progress=progress, task_id=task_id)

        result = TimeEntries()
        if data:
            # Cache all referenced objects
            self.get_users(progress=progress)
            self.get_contacts(progress=progress)
            self.get_projects(progress=progress)

            for datum in data:
                entry = TimeEntry(datum)
                entry.started_at = parse_timestamp(datum['started_at'])
                entry.ended_at = parse_timestamp(datum['ended_at'])

                project_id = datum.get('project_id') or None
                if project_id:
                    entry.project = self.get_project(int(project_id))

                contact_id = datum.get('contact_id') or None
                if contact_id:
                    entry.contact = self.get_contact(int(contact_id))

                user_id = datum.get('user_id') or None
                if user_id:
                    entry.user = self.get_user(int(user_id))

                result.append(entry)

        return result

    def create_time_entry(self, data, **kwargs) -> TimeEntry:
        return self._request('POST', 'time_entries', {'time_entry': data}, **kwargs)

    def update_time_entry(self, id, changes, **kwargs):
        return self._request('PATCH', f'time_entries/{id}', {'time_entry': changes}, **kwargs)

    def delete_time_entry(self, id, **kwargs):
        return self._request('DELETE', f'time_entries/{id}', **kwargs)

    def get_sales_invoices(self, *, state=None, contact=None, progress=None) -> Sequence[SalesInvoice]:
        filters = []
        if state:
            filters.append(f'state:{state}')
        if contact:
            filters.append(f'contact:{contact.id}')

        if progress:
            task_id = progress.add_task('Fetching sales invoices...', total=1)
        else:
            task_id = None

        invoices = []
        for data in self._request('GET', 'sales_invoices', filters=filters, progress=progress):
            invoice = SalesInvoice(data)
            invoice.contact = self.get_contact(int(data['contact_id']))
            invoice.details = []
            for detail_data in data['details']:
                project_id = detail_data.get('project_id')
                tax_rate_id = detail_data.get('tax_rate_id')
                ledger_account_id = detail_data.get('ledger_account_id')

                detail = SalesInvoice.Detail(detail_data)
                if project_id:
                    detail.project = self.get_project(int(project_id))
                if tax_rate_id:
                    detail.tax_rate = self.get_tax_rate(int(tax_rate_id))
                if ledger_account_id:
                    detail.ledger_account = self.get_ledger_account(int(ledger_account_id))
                invoice.details.append(detail)

            invoices.append(invoice)

        return invoices

    def create_sales_invoice(self, data, **kwargs):
        return self._request('POST', 'sales_invoices', {'sales_invoice': data}, **kwargs)


class Credentials:
    def __init__(self, access_token, refresh_token=None):
        self.access_token = access_token
        self.refresh_token = refresh_token

    @staticmethod
    def from_keyring(keyring, username):
        data = keyring.get_password('name.rdb.toggl2moneybird.moneybird-credentials', username)
        if data:
            return Credentials(*data.split('|', 1))
        else:
            return None

    def store_keyring(self, keyring, username):
        data = self.access_token
        if self.refresh_token:
            data += '|' + self.refresh_token
        keyring.set_password('name.rdb.toggl2moneybird.moneybird-credentials', username, data)

    @staticmethod
    def erase_keyring(keyring, username):
        keyring.delete_password('name.rdb.toggl2moneybird.moneybird-credentials', username)


def authenticate(refresh_token=None):
    # Spin up a temporary web server to handle the redirect from Moneybird.
    # Unfortunately we can't just look for an open port, since the redirect URI
    # is fixed in the Moneybird client registration.
    server = _OAuthServer()

    scope = '%20'.join(API_SCOPES)
    redirect_uri = f'http://localhost:{LOCALHOST_PORT}'
    webbrowser.open(f'https://moneybird.com/oauth/authorize?client_id={CLIENT_ID}&redirect_uri={redirect_uri}&response_type=code&scope={scope}')
    while not server.oauth_error and not server.oauth_code:
        server.handle_request()

    if server.oauth_error:
        print("Authentication failed:", server.oauth_error)
        return None

    code = server.oauth_code
    server.server_close()

    r = requests.post(f'https://moneybird.com/oauth/token?client_id={CLIENT_ID}&client_secret={CLIENT_SECRET}&redirect_uri={redirect_uri}&code={code}&grant_type=authorization_code')
    data = r.json()
    return Credentials(data['access_token'], data.get('refresh_token'))


def get_administrations(credentials):
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + credentials.access_token,
    }

    url = f'https://moneybird.com/api/v2/administrations.json'
    r = requests.get(url, headers=headers)
    if r.status_code >= 300:
        raise APIError(r.status_code)

    admins = []
    for data in r.json():
        admins.append(Administration(data, headers))
    return admins

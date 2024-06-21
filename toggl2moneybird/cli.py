#!python3

__all__ = 'main',

import sys
import keyring
import getpass
from datetime import datetime, date
from argparse import ArgumentParser

from rich.console import Console
from rich_argparse import RichHelpFormatter

from . import moneybird as mb
from . import commands


def main():
    console = Console()

    cmd_choices = [name[4:] for name in dir(commands) if name.startswith('cmd_')]
    cmd_choices.append('help')

    parser = ArgumentParser(prog='toggl2moneybird', description='Synchronizes Toggl Track time entries with a Moneybird administration', formatter_class=RichHelpFormatter)
    parser.add_argument('command', choices=cmd_choices, default='sync')
    parser.add_argument('-n', action='store_true', dest='dry_run', help="Does not perform any mutations")
    parser.add_argument('-y', action='store_true', dest='yes', help="Do not ask for confirmation")
    parser.add_argument('--project', action='append', metavar='"Project"', dest='projects', help="Limit to the given project (may be repeated)")
    parser.add_argument('--exclude-tag', action='append', metavar='"tag"', dest='exclude_tags', help="Exclude entries with the given tag (may be repeated)")
    parser.add_argument('--unbillable', action='store_false', dest='only_billable', help="Include unbillable entries")
    parser.add_argument('--unbillable-tag', action='store', dest='unbillable_tag', help="Consider all entries billable except those with the given tag")
    parser.add_argument('--rate', action='store', dest='rate', type=float, help="Use the given rate for invoices, overrides rate in Toggl Track")
    parser.add_argument('--currency', action='store', dest='currency', help="Use the given currency for invoices (e.g. EUR), overrides currency in Toggl Track")
    args = parser.parse_args()

    if args.command == 'help':
        parser.print_help()
        return

    logname = getpass.getuser()
    mb_creds = mb.Credentials.from_keyring(keyring, logname)
    if not mb_creds:
        mb_creds = mb.authenticate()
        if not mb_creds:
            print("Authentication failed.")
            sys.exit(1)

        mb_creds.store_keyring(keyring, logname)

    mb_admins = mb.get_administrations(mb_creds)
    mb_admin = mb_admins[0]

    console.print("Logged into [deep_sky_blue1 bold]moneybird[/deep_sky_blue1 bold] administration", mb_admin)

    cmd_func = getattr(commands, 'cmd_' + args.command)
    return cmd_func(console, args, mb_admin)

__all__ = 'Menu',

import os

from rich.live import Live
from rich.table import Table
from rich.console import Group, Console
from rich.text import Text
from rich.control import Control
from rich.prompt import Prompt

have_getch = True

if not have_getch:
    pass
elif os.name == 'nt':
    from msvcrt import getwch
else:
    import tty
    import termios
    import sys

    def getwch():
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


class Menu:
    def __init__(self, *, console=None, prompt=None, show_edge=True, show_header=True, show_footer=False, default=None):
        self.console = console or Console()
        self.prompt = prompt
        self.show_edge = show_edge
        self.show_header = show_header
        self.show_footer = show_footer
        self.default = default
        self._columns = []
        self._rows = []
        self.filter = None

    def add_column(self, *args, **kwargs):
        self._columns.append((args, kwargs))

    def add_row(self, *args, value):
        self._rows.append((args, value))

    def choose(self, multiple=False):
        orig_rows = self._rows
        rows = self._rows

        q = ''
        if self.default and have_getch:
            for i, (cells, value) in enumerate(rows):
                if value == self.default:
                    break
            else:
                i = -1 if self.filter else 0
        else:
            i = -1 if self.filter else 0
        default_i = i
        count = 1

        with Live(None, console=self.console, auto_refresh=False, transient=True) as live:
            while True:
                table = Table(show_edge=self.show_edge, show_header=self.show_header, show_footer=self.show_footer)
                if not have_getch:
                    table.add_column("", justify="right", style="bold")

                for args, kwargs in self._columns:
                    table.add_column(*args, **kwargs)

                if i >= len(rows):
                    i = len(rows) - 1

                for j, (cells, value) in enumerate(rows):
                    if have_getch:
                        reverse = (len(rows) == 1 or (j >= i and j < i + count))
                        table.add_row(*cells, style='reverse' if reverse else '')
                    else:
                        table.add_row(str(j + 1), *cells)

                if have_getch:
                    if self.filter:
                        filter_text = Text.assemble(Text.from_markup(self.prompt), " ", (q, 'magenta bold'), (' ', 'reverse blink'))
                    else:
                        filter_text = self.prompt or Text.assemble("Use arrows to select:")

                    group = Group(filter_text, table)
                    live.update(group, refresh=True)

                    c = getwch()
                    if c == '\b' or c == '\x7f':
                        if q:
                            q = q[:-1]
                        if not q and i < 0 and default_i >= 0:
                            i = default_i
                    elif c == '\003':
                        raise KeyboardInterrupt
                    elif c == '\n' or c == '\r':
                        pass
                    elif c == '\t':
                        i += 1
                        if i >= len(rows):
                            i = 0
                    elif c == '\x1b':  # ESC, Unix
                        c = getwch()
                        if c == '[':
                            c = getwch()
                            if c == '1':
                                c = getwch()
                                if c == ';':
                                    c = getwch()
                                    if c == '2':
                                        c = getwch()
                                        if multiple:
                                            if c == 'A':
                                                if i >= 0:
                                                    i -= 1
                                                    count += 1
                                            elif c == 'B':
                                                count += 1
                                                if i + count >= len(rows):
                                                    count = len(rows) - i
                                            continue

                            if c == 'A' or c == 'Z':  # up or back-tab
                                if count == 1 or i > 0:
                                    i -= 1
                                    if i < 0:
                                        i = len(rows) - 1
                            elif c == 'B':
                                i += count
                                if i >= len(rows):
                                    i = 0
                            count = 1
                        continue
                    elif (c == '\x00' or c == '\xe0') and os.name == 'nt':  # ESC, Windows
                        # We can't detect a genuine a-with-grave-accent here,
                        # but if we see that the second character was something
                        # unlikely to be a scancode we'll retroactively input
                        # this as two characters.
                        #FIXME: doesn't handle case if next char is a control
                        # character correctly yet.
                        next_c = getwch()
                        if next_c == 'H':  # up
                            i -= 1
                            if i < 0:
                                i = len(rows) - 1
                            continue
                        elif next_c == 'P':  # down
                            i += 1
                            if i >= len(rows):
                                i = 0
                            continue
                        elif c == '\xe0' and ((ord(next_c) >= 0x20 and ord(next_c) <= 0x39) or ord(next_c) >= 0x61):
                            q += c
                            i = -1
                        else:
                            continue
                    elif c.isprintable() and self.filter:
                        q += c
                        i = -1
                else:
                    if self.filter:
                        live.update(Group(self.prompt, table, Text("Enter number of option, or part of name to filter: ")), refresh=True)
                    elif multiple:
                        live.update(Group(self.prompt, table, Text("Enter (comma-separated) number(s) of option(s): ")), refresh=True)
                    else:
                        live.update(Group(self.prompt, table, Text("Enter number of option: ")), refresh=True)

                    self.console.print(Control.show_cursor(True))
                    q = input().strip()
                    self.console.print(Control.show_cursor(False), Control.move(0, -1))
                    try:
                        if multiple:
                            results = []
                            items = q.split(',')
                            for item in items:
                                if '-' in item:
                                    first, last = item.split('-', 1)
                                    first = int(first.strip()) - 1
                                    last = int(last.strip()) - 1
                                    assert first >= 0
                                    assert last > first
                                    for i in range(first, last + 1):
                                        results.append(rows[i][1])
                                else:
                                    i = int(item.strip()) - 1
                                    results.append(rows[i][1])

                            return results
                        else:
                            i = int(q) - 1
                            assert i >= 0
                            return rows[i][1]
                    except Exception:
                        pass

                # Check matches.
                if self.filter and q:
                    rows = []
                    for row in orig_rows:
                        if self.filter(row[1], q):
                            rows.append(row)

                    if not have_getch:
                        if not rows:
                            rows = orig_rows
                            q = ''
                        elif len(rows) == 1:
                            if multiple:
                                return [rows[0][1]]
                            else:
                                return rows[0][1]
                else:
                    rows = orig_rows

                if have_getch and (c == '\n' or c == '\r'):
                    if len(rows) == 1 or (i >= 0 and i < len(rows)):
                        if multiple:
                            return [row[1] for row in rows[i:i+count]]
                        else:
                            return rows[i][1]
                    #elif len(rows) == 0 or (i < 0 and not q):
                    #    return None

    @staticmethod
    def ask(prompt, items, **kwargs):
        default = kwargs.get('default')
        if default and not have_getch:
            prompt = f'{prompt} [cyan bold]({default.__rich__()})[/cyan bold]'

        kwargs['show_header'] = False
        kwargs['show_edge'] = False
        kwargs['prompt'] = f'{prompt}:'

        menu = Menu(**kwargs)
        menu.filter = lambda item, q: item.matches(q)
        menu.add_column('')
        for item in items:
            menu.add_row(item.__rich__(), value=item)
        choice = menu.choose()
        menu.console.print(f'{prompt}:', choice)
        return choice

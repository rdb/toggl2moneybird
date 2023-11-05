#!python3

__all__ = ()

from .cli import main

from rich.console import Console

try:
    main()
except Exception:
    console = Console()
    console.print()
    console.print_exception(extra_lines=0, width=console.width)

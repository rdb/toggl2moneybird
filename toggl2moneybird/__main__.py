#!python3

__all__ = ()

from .cli import main

try:
    main()
except Exception:
    console = Console()
    console.print()
    console.print_exception(extra_lines=0, width=console.width)

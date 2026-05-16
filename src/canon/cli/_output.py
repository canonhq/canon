"""Shared CLI output utilities built on rich.

Every CLI command should import from here for consistent formatting.
Centralizes console, themes, tables, spinners, status badges, and prompts.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# ── Theme ──────────────────────────────────────────────────

CANON_THEME = Theme(
    {
        "success": "green",
        "error": "red",
        "warning": "yellow",
        "info": "blue",
        "muted": "dim",
        "heading": "bold",
        "key": "cyan",
    }
)

# Singleton consoles — stderr for diagnostics, stdout for data.
# These are mutable module-level objects. configure() mutates _no_color
# and callers always access the current value via the module attribute,
# so reassignment is safe as long as no module caches the reference at
# import time.  To avoid stale-binding bugs, console and stdout_console
# are set once here and configure() replaces them *in the module dict*
# so that ``from ._output import stdout_console`` done *after*
# configure() picks up the right object.  For imports done *before*
# configure() (which is the common case for command modules loaded at
# registration time), we expose ``get_console()`` / ``get_stdout()``
# accessor functions that always return the current module-level object.
console: Console = Console(theme=CANON_THEME, stderr=True, highlight=False)
stdout_console: Console = Console(theme=CANON_THEME, highlight=False)

# Global quiet flag — commands check this before non-essential output.
_quiet = False


def get_console() -> Console:
    """Return the current stderr console (always up-to-date after configure)."""
    return console


def get_stdout() -> Console:
    """Return the current stdout console (always up-to-date after configure)."""
    return stdout_console


def configure(*, no_color: bool = False, quiet: bool = False, verbose: bool = False) -> None:
    """Apply global CLI flags to the output module.

    Called once from main() after parsing global args.
    """
    global _quiet
    _quiet = quiet

    if no_color:
        os.environ["NO_COLOR"] = "1"
        # Replace module-level consoles so get_console()/get_stdout()
        # return the right objects.
        global console, stdout_console
        console = Console(theme=CANON_THEME, stderr=True, highlight=False, no_color=True)
        stdout_console = Console(theme=CANON_THEME, highlight=False, no_color=True)

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")


def is_quiet() -> bool:
    return _quiet


# ── Helpers ────────────────────────────────────────────────


def print_error(msg: str, *, hint: str | None = None) -> None:
    """Print a styled error to stderr."""
    c = get_console()
    c.print(f"[error]error:[/error] {msg}")
    if hint:
        c.print(f"  [muted]{hint}[/muted]")


def print_warning(msg: str, *, hint: str | None = None) -> None:
    """Print a styled warning to stderr."""
    c = get_console()
    c.print(f"[warning]warning:[/warning] {msg}")
    if hint:
        c.print(f"  [muted]{hint}[/muted]")


def print_success(msg: str, *, hint: str | None = None) -> None:
    """Print a styled success message to stdout."""
    c = get_stdout()
    c.print(f"[success]{msg}[/success]")
    if hint:
        c.print(f"  [muted]{hint}[/muted]")


# ── Tables ─────────────────────────────────────────────────


def make_table(
    title: str | None = None,
    columns: list[dict[str, Any]] | None = None,
    rows: list[list[Any]] | None = None,
) -> Table:
    """Create a consistently styled table.

    Columns are dicts with keys: name, style, justify, min_width.
    """
    table = Table(
        title=title,
        title_style="heading",
        show_header=True,
        header_style="muted",
        box=None,
        pad_edge=False,
        padding=(0, 2),
    )
    for col in columns or []:
        table.add_column(
            col.get("name", ""),
            style=col.get("style"),
            justify=col.get("justify", "left"),
            min_width=col.get("min_width"),
            no_wrap=col.get("no_wrap", False),
        )
    for row in rows or []:
        table.add_row(*[str(v) if not isinstance(v, Text) else v for v in row])
    return table


# ── Progress & Spinners ───────────────────────────────────


@contextmanager
def spinner(message: str) -> Iterator[None]:
    """Show a spinner on stderr while a block runs."""
    if _quiet or not console.is_terminal:
        yield
        return

    with console.status(f"[info]{message}[/info]", spinner="dots"):
        yield


@contextmanager
def progress_bar(total: int, description: str = "") -> Iterator[Progress]:
    """Show a progress bar on stderr for counted operations."""
    if _quiet or not console.is_terminal:
        # Silent progress: stderr console with no_color avoids visible output
        # without leaking file descriptors.
        p = Progress(console=Console(stderr=True, no_color=True, highlight=False))
        task_id = p.add_task(description, total=total)
        _orig_advance = p.advance

        def _advance(n: int = 1) -> None:
            _orig_advance(task_id, n)

        p.advance = _advance  # type: ignore[assignment]
        yield p
        return

    p = Progress(
        SpinnerColumn(),
        TextColumn("[info]{task.description}[/info]"),
        BarColumn(),
        TextColumn("[muted]{task.completed}/{task.total}[/muted]"),
        TimeElapsedColumn(),
        console=console,
    )
    task_id = p.add_task(description, total=total)
    _orig_advance = p.advance

    def _advance(n: int = 1) -> None:
        _orig_advance(task_id, n)

    p.advance = _advance  # type: ignore[assignment]

    with p:
        yield p


# ── Status Badges ─────────────────────────────────────────

_STATUS_STYLES: dict[str, str] = {
    "done": "green",
    "in_progress": "yellow",
    "todo": "dim",
    "blocked": "red",
    "draft": "dim italic",
    "deprecated": "dim strikethrough",
}

_RESULT_STYLES: dict[str, tuple[str, str]] = {
    "pass": ("PASS", "green bold"),
    "warn": ("WARN", "yellow bold"),
    "fail": ("FAIL", "red bold"),
    "skip": ("SKIP", "dim"),
}


def status_badge(status: str) -> Text:
    """Return styled text for a spec section status."""
    style = _STATUS_STYLES.get(status, "")
    return Text(status, style=style)


def result_badge(result: str) -> Text:
    """Return styled text for a check result (pass/warn/fail/skip)."""
    label, style = _RESULT_STYLES.get(result, (result.upper(), ""))
    return Text(label, style=style)


def coverage_style(pct: float) -> str:
    """Return a style string for a coverage percentage."""
    if pct >= 80:
        return "green"
    if pct >= 50:
        return "yellow"
    return "red"


def coverage_text(pct: float, label: str | None = None) -> Text:
    """Return styled coverage percentage text."""
    display = label or f"{pct:.0f}%"
    return Text(display, style=coverage_style(pct))


# ── Prompts ───────────────────────────────────────────────


def prompt(message: str, default: str = "") -> str:
    """Prompt the user for input with an optional default."""
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"  {message}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)
    return value or default


def prompt_confirm(message: str, default: bool = True) -> bool:
    """Ask a yes/no question."""
    hint = "Y/n" if default else "y/N"
    try:
        raw = input(f"  {message} [{hint}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)
    if not raw:
        return default
    return raw in ("y", "yes")


def prompt_choice(message: str, choices: list[str], default: str = "") -> str:
    """Present a numbered menu and return the selected value."""
    print(f"\n  {message}")
    for i, choice in enumerate(choices, 1):
        marker = "*" if choice == default else " "
        print(f"    {marker}{i}. {choice}")

    default_idx = choices.index(default) + 1 if default in choices else ""
    try:
        raw = input(f"  Choice [{default_idx}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(1)

    if not raw and default:
        return default
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(choices):
            return choices[idx]
    except (ValueError, IndexError):
        pass
    # Accept text input matching a choice name (e.g. "github" instead of "1")
    if raw in choices:
        return raw
    fallback = default or (choices[0] if choices else "")
    print(f"  Invalid choice — using: {fallback}")
    return fallback

"""SkopaqTrader CLI theme — color constants and Rich Console singleton."""

from __future__ import annotations

from rich.console import Console

# ── Shared Console ────────────────────────────────────────────────────────────
# All CLI output goes through this single instance for consistent width/style.
console = Console()

# ── Brand Colors ──────────────────────────────────────────────────────────────

BRAND = "bold cyan"
BRAND_DIM = "cyan"
SUCCESS = "bold green"
WARNING = "bold yellow"
ERROR = "bold red"
DIM = "dim"
ACCENT = "magenta"
MUTED = "grey62"

# ── Panel Border Styles ───────────────────────────────────────────────────────

HEADER_BORDER = "cyan"
STATUS_BORDER = "green"
ERROR_BORDER = "red"
WARNING_BORDER = "yellow"
INFO_BORDER = "blue"

# ── Status Indicators ────────────────────────────────────────────────────────

OK = "[bold green]\u2713[/bold green]"       # ✓
WARN = "[bold yellow]\u25b2[/bold yellow]"   # ▲
FAIL = "[bold red]\u2717[/bold red]"         # ✗
DOT = "[dim]\u2022[/dim]"                    # •

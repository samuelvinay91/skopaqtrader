"""Rich display functions for every SkopaqTrader CLI command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Sequence

from rich import box
from rich.align import Align
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from skopaq.cli.theme import (
    ACCENT,
    BRAND,
    BRAND_DIM,
    DIM,
    ERROR,
    ERROR_BORDER,
    FAIL,
    HEADER_BORDER,
    INFO_BORDER,
    MUTED,
    OK,
    STATUS_BORDER,
    SUCCESS,
    WARN,
    WARNING,
    WARNING_BORDER,
    console,
)

if TYPE_CHECKING:
    from skopaq.broker.models import ExecutionResult, TradingSignal
    from skopaq.broker.token_manager import TokenHealth
    from skopaq.config import SkopaqConfig
    from skopaq.graph.skopaq_graph import AnalysisResult
    from skopaq.scanner.models import ScannerCandidate

_STATIC_DIR = Path(__file__).parent / "static"


# ── Welcome Banner ────────────────────────────────────────────────────────────


def display_welcome() -> None:
    """Show branded ASCII art welcome banner with workflow summary."""
    banner_path = _STATIC_DIR / "welcome.txt"
    if banner_path.exists():
        ascii_art = banner_path.read_text()
    else:
        ascii_art = "  SkopaqTrader"

    content = Text()
    content.append(ascii_art, style=BRAND_DIM)
    content.append("\n")
    content.append(
        "India's first self-evolving AI algorithmic trading platform\n",
        style="bold white",
    )
    content.append("Powered by INDstocks  ", style=DIM)
    content.append("|  ", style=DIM)
    content.append("Built on TradingAgents", style=DIM)
    content.append("\n\n")
    content.append("Workflow:  ", style="bold")
    content.append("Analysts", style="cyan")
    content.append(" \u2192 ", style=DIM)
    content.append("Researchers", style="green")
    content.append(" \u2192 ", style=DIM)
    content.append("Trader", style="yellow")
    content.append(" \u2192 ", style=DIM)
    content.append("Risk", style="magenta")
    content.append(" \u2192 ", style=DIM)
    content.append("Execution", style="bold green")

    panel = Panel(
        Align.center(content),
        border_style=HEADER_BORDER,
        padding=(1, 2),
        title="[bold cyan]SkopaqTrader[/bold cyan]",
        subtitle="[dim]Multi-Agent AI Trading Framework[/dim]",
    )
    console.print(panel)
    console.print()


# ── Status Command ────────────────────────────────────────────────────────────


def display_status(
    version: str,
    config: SkopaqConfig,
    health: TokenHealth,
    llms: list[str],
) -> None:
    """Render the full ``skopaq status`` dashboard."""
    table = Table(
        show_header=False,
        box=box.SIMPLE,
        padding=(0, 2),
        expand=True,
    )
    table.add_column("Key", style="bold", width=14)
    table.add_column("Value")

    # Version
    table.add_row("Version", f"[{BRAND}]v{version}[/{BRAND}]")

    # Mode
    mode = config.trading_mode.upper()
    mode_style = SUCCESS if mode == "PAPER" else "bold red"
    table.add_row("Mode", f"[{mode_style}]{mode}[/{mode_style}]")

    # Broker
    table.add_row("Broker", f"INDstocks ({config.indstocks_base_url})")

    # Token
    if health.valid:
        table.add_row(
            "Token",
            f"{OK}  VALID ({health.remaining} remaining)",
        )
        if health.warning:
            table.add_row("", f"{WARN}  {health.warning}")
    else:
        table.add_row(
            "Token",
            f"{FAIL}  INVALID \u2014 {health.warning}",
        )

    # Supabase
    if config.supabase_url:
        table.add_row("Supabase", f"{OK}  configured")
    else:
        table.add_row("Supabase", f"{WARN}  NOT configured")

    # LLMs
    if llms:
        llm_text = ", ".join(f"[{ACCENT}]{name}[/{ACCENT}]" for name in llms)
        table.add_row("LLMs", llm_text)
    else:
        table.add_row("LLMs", f"{FAIL}  NONE configured")

    # Redis
    if config.upstash_redis_url:
        table.add_row("Redis", f"{OK}  Upstash")
    else:
        table.add_row("Redis", f"{WARN}  NOT configured")

    panel = Panel(
        table,
        title="[bold]System Health[/bold]",
        border_style=STATUS_BORDER,
        padding=(1, 1),
    )
    console.print(panel)


# ── Analyze Command ───────────────────────────────────────────────────────────


def display_analyze_start(symbol: str, date: str) -> None:
    """Show analysis start banner."""
    console.print(
        Rule(
            f"[{BRAND}]Analyzing {symbol} for {date}[/{BRAND}]",
            style=BRAND_DIM,
        )
    )


def display_analyze_result(result: AnalysisResult) -> None:
    """Render agent analysis result with signal table and reasoning."""
    if result.error:
        display_error(result.error)
        return

    signal = result.signal
    if not signal:
        display_info("No signal generated.")
        _display_duration(result.duration_seconds)
        return

    # ── Signal summary table ──
    table = Table(
        show_header=False,
        box=box.ROUNDED,
        padding=(0, 2),
        expand=True,
        title=f"[bold]{result.symbol}[/bold]  \u2502  {result.trade_date}",
        title_style="bold",
    )
    table.add_column("Field", style="bold", width=12)
    table.add_column("Value")

    # Action with color
    action_style = _action_style(signal.action)
    table.add_row(
        "Action",
        f"[{action_style}]{signal.action}[/{action_style}]",
    )

    # Confidence bar
    conf = signal.confidence
    conf_style = SUCCESS if conf >= 70 else WARNING if conf >= 40 else ERROR
    bar = _confidence_bar(conf)
    table.add_row("Confidence", f"[{conf_style}]{conf}%[/{conf_style}]  {bar}")

    if signal.entry_price is not None:
        table.add_row("Entry", f"\u20b9 {signal.entry_price:,.2f}")
    if signal.stop_loss is not None:
        table.add_row("Stop Loss", f"[red]\u20b9 {signal.stop_loss:,.2f}[/red]")
    if signal.target is not None:
        table.add_row("Target", f"[green]\u20b9 {signal.target:,.2f}[/green]")

    panel = Panel(
        table,
        title="[bold cyan]Analysis Signal[/bold cyan]",
        border_style=HEADER_BORDER,
        padding=(1, 1),
    )
    console.print(panel)

    # ── Reasoning ──
    if signal.reasoning:
        reasoning_text = signal.reasoning[:500]
        if len(signal.reasoning) > 500:
            reasoning_text += "..."
        console.print(
            Panel(
                Markdown(reasoning_text),
                title="[bold]Reasoning[/bold]",
                border_style=INFO_BORDER,
                padding=(1, 2),
            )
        )

    _display_duration(result.duration_seconds)


# ── Trade Command ─────────────────────────────────────────────────────────────


def display_trade_start(symbol: str, date: str, mode: str) -> None:
    """Show trade start banner."""
    mode_badge = f"[bold green]{mode.upper()}[/bold green]"
    console.print(
        Rule(
            f"[{BRAND}]Trading {symbol} for {date}[/{BRAND}]  [{DIM}]{mode_badge}[/{DIM}]",
            style=BRAND_DIM,
        )
    )


def display_trade_result(result: AnalysisResult) -> None:
    """Render trade execution result."""
    if result.error:
        display_error(result.error)
        return

    # Show signal first
    if result.signal:
        action_style = _action_style(result.signal.action)
        console.print(
            f"  Signal: [{action_style}]{result.signal.action}[/{action_style}]"
            f"  (confidence={result.signal.confidence}%)"
        )

    ex = result.execution
    if not ex:
        display_info("No execution (HOLD or no signal).")
        _display_duration(result.duration_seconds)
        return

    # ── Execution details table ──
    table = Table(
        show_header=False,
        box=box.ROUNDED,
        padding=(0, 2),
        expand=True,
    )
    table.add_column("Field", style="bold", width=14)
    table.add_column("Value")

    if ex.success:
        table.add_row("Status", f"{OK}  [bold green]FILLED[/bold green]")
        table.add_row("Mode", ex.mode.upper())
        if ex.fill_price is not None:
            table.add_row("Fill Price", f"\u20b9 {ex.fill_price:,.2f}")
        table.add_row("Slippage", f"{ex.slippage:.4f}")
        table.add_row("Brokerage", f"\u20b9 {ex.brokerage:.2f}")
        border = STATUS_BORDER
    else:
        table.add_row("Status", f"{FAIL}  [bold red]REJECTED[/bold red]")
        table.add_row("Reason", f"[red]{ex.rejection_reason}[/red]")
        border = ERROR_BORDER

    panel = Panel(
        table,
        title="[bold]Execution Result[/bold]",
        border_style=border,
        padding=(1, 1),
    )
    console.print(panel)
    _display_duration(result.duration_seconds)


# ── Scan Command ──────────────────────────────────────────────────────────────


def display_scan_start() -> None:
    """Show scanner start banner."""
    console.print(Rule(f"[{BRAND}]Scanner Cycle[/{BRAND}]", style=BRAND_DIM))


def display_scan_results(candidates: Sequence[ScannerCandidate]) -> None:
    """Render scanner results as a styled table."""
    if not candidates:
        display_info("No candidates found.")
        return

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        padding=(0, 1),
        expand=True,
    )
    table.add_column("Symbol", style="bold cyan", width=14)
    table.add_column("Urgency", justify="center", width=10)
    table.add_column("Reason", no_wrap=False, ratio=1)

    for c in candidates:
        # Color urgency badge
        if c.urgency == "high":
            urgency = "[bold red]HIGH[/bold red]"
        elif c.urgency == "low":
            urgency = f"[{DIM}]LOW[/{DIM}]"
        else:
            urgency = f"[{WARNING}]NORMAL[/{WARNING}]"

        table.add_row(c.symbol, urgency, c.reason)

    panel = Panel(
        table,
        title=f"[bold]Scanner Results[/bold]  [{DIM}]{len(candidates)} candidate(s)[/{DIM}]",
        border_style=HEADER_BORDER,
        padding=(1, 1),
    )
    console.print(panel)


# ── Token Commands ────────────────────────────────────────────────────────────


def display_token_health(health: TokenHealth) -> None:
    """Render token health as a styled panel."""
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2), expand=True)
    table.add_column("Key", style="bold", width=12)
    table.add_column("Value")

    if health.valid:
        table.add_row("Status", f"{OK}  [bold green]VALID[/bold green]")
        if health.expires_at:
            table.add_row("Expires", str(health.expires_at))
        if health.remaining:
            table.add_row("Remaining", str(health.remaining))
        if health.warning:
            table.add_row("Warning", f"{WARN}  [{WARNING}]{health.warning}[/{WARNING}]")
        border = STATUS_BORDER
    else:
        table.add_row("Status", f"{FAIL}  [bold red]INVALID[/bold red]")
        if health.warning:
            table.add_row("Reason", f"[red]{health.warning}[/red]")
        border = ERROR_BORDER

    panel = Panel(
        table,
        title="[bold]Token Health[/bold]",
        border_style=border,
        padding=(1, 1),
    )
    console.print(panel)


def display_token_set(health: TokenHealth) -> None:
    """Confirm token was stored successfully."""
    content = Text()
    content.append(f"{OK}  ", style="")
    content.append("Token stored successfully\n\n", style=SUCCESS)
    if health.expires_at:
        content.append("Expires:   ", style="bold")
        content.append(f"{health.expires_at}\n")
    if health.remaining:
        content.append("Remaining: ", style="bold")
        content.append(f"{health.remaining}")

    console.print(
        Panel(content, border_style=STATUS_BORDER, padding=(1, 2))
    )


# ── Serve Command ─────────────────────────────────────────────────────────────


def display_serve_banner(host: str, port: int) -> None:
    """Show server startup banner."""
    content = Text()
    content.append("SkopaqTrader API\n", style=BRAND)
    content.append(f"Listening on ", style=DIM)
    content.append(f"http://{host}:{port}", style="bold underline")
    content.append(f"\n")
    content.append("Health:    ", style="bold")
    content.append(f"http://{host}:{port}/health", style=DIM)

    console.print(
        Panel(
            Align.center(content),
            border_style=STATUS_BORDER,
            padding=(1, 2),
            title="[bold]Server[/bold]",
        )
    )


# ── Version Command ───────────────────────────────────────────────────────────


def display_version(version: str) -> None:
    """Show styled version text."""
    console.print(f"[{BRAND}]SkopaqTrader[/{BRAND}] [{DIM}]v{version}[/{DIM}]")


# ── Generic Messages ──────────────────────────────────────────────────────────


def display_error(message: str) -> None:
    """Show error message in a red-bordered panel."""
    console.print(
        Panel(
            f"{FAIL}  [{ERROR}]{message}[/{ERROR}]",
            border_style=ERROR_BORDER,
            title="[bold red]Error[/bold red]",
            padding=(0, 2),
        )
    )


def display_info(message: str) -> None:
    """Show informational message in a blue-bordered panel."""
    console.print(
        Panel(
            f"[{BRAND_DIM}]{message}[/{BRAND_DIM}]",
            border_style=INFO_BORDER,
            padding=(0, 2),
        )
    )


def display_success(message: str) -> None:
    """Show success message in a green-bordered panel."""
    console.print(
        Panel(
            f"{OK}  [{SUCCESS}]{message}[/{SUCCESS}]",
            border_style=STATUS_BORDER,
            padding=(0, 2),
        )
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _action_style(action: str) -> str:
    """Return Rich style for a trading action."""
    return {
        "BUY": "bold green",
        "SELL": "bold red",
        "HOLD": "bold yellow",
    }.get(action.upper(), "bold white")


def _confidence_bar(confidence: int, width: int = 20) -> str:
    """Render a simple text-based confidence bar."""
    filled = round(confidence / 100 * width)
    empty = width - filled
    return f"[green]{'█' * filled}[/green][dim]{'░' * empty}[/dim]"


def _display_duration(seconds: float) -> None:
    """Show elapsed time footer."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    if mins > 0:
        elapsed = f"{mins}m {secs}s"
    else:
        elapsed = f"{secs}s"
    console.print(f"  [{MUTED}]\u23f1 {elapsed}[/{MUTED}]")

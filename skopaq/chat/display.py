"""Rich display helpers for the interactive chatbot.

Handles streaming token output, tool invocation panels, and branded
chat UI elements.  Reuses the color constants from ``skopaq/cli/theme.py``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

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

logger = logging.getLogger(__name__)

# ── Tool name → display name mapping ────────────────────────────────────────

_TOOL_DISPLAY = {
    "analyze_stock": ("Analyzing", "cyan"),
    "trade_stock": ("Trading", "green"),
    "scan_market": ("Scanning", "magenta"),
    "get_portfolio": ("Portfolio", "blue"),
    "get_quote": ("Quote", "yellow"),
    "get_orders": ("Orders", "blue"),
    "check_status": ("Status", "cyan"),
    "compute_position_size": ("Position Size", "magenta"),
    "check_safety": ("Safety Check", "yellow"),
    "get_market_data": ("Market Data", "cyan"),
}


# ── Welcome / Banners ───────────────────────────────────────────────────────


def display_chat_welcome(mode: str, asset_class: str, version: str) -> None:
    """Show branded chat welcome banner."""
    content = Text()
    content.append("\n  SkopaqTrader Chat", style=BRAND)
    content.append(" v" + version, style=DIM)
    content.append("\n  Interactive AI Trading Assistant\n", style="bold white")
    content.append(f"\n  Mode: ", style=DIM)
    content.append(
        mode.upper(),
        style=SUCCESS if mode == "paper" else ERROR,
    )
    content.append(f"  |  Asset: ", style=DIM)
    content.append(asset_class.upper(), style=ACCENT)
    content.append("\n")
    content.append(
        "\n  Type your question or use /help for commands.\n"
        "  Press Ctrl+C to cancel, Ctrl+D to exit.\n",
        style=MUTED,
    )

    console.print(
        Panel(
            content,
            border_style=HEADER_BORDER,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )
    console.print()


def display_chat_goodbye() -> None:
    """Show exit message."""
    console.print("\n  Goodbye!", style=BRAND_DIM)
    console.print()


# ── Slash Command Help ────��─────────────────────────────────────────────────


def display_help() -> None:
    """Show available slash commands."""
    table = Table(
        title="Commands",
        box=box.SIMPLE_HEAVY,
        title_style=BRAND,
        show_header=True,
        header_style="bold",
        padding=(0, 2),
    )
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description")

    commands = [
        ("/help", "Show this help"),
        ("/scan [N]", "Scan market for top N candidates"),
        ("/portfolio", "Show positions, holdings, and funds"),
        ("/positions", "Alias for /portfolio"),
        ("/orders", "Show today's orders"),
        ("/quote SYMBOL", "Get real-time quote"),
        ("/status", "System health check"),
        ("/mode [paper|live]", "Show or switch trading mode"),
        ("/history", "Show conversation summary"),
        ("/clear", "Clear conversation history"),
        ("/exit, /quit", "Exit chatbot"),
    ]
    for cmd, desc in commands:
        table.add_row(cmd, desc)

    console.print()
    console.print(table)
    console.print()
    console.print(
        "  Or just type naturally: ",
        style=DIM,
        end="",
    )
    console.print(
        '"analyze RELIANCE", "what should I trade today?"',
        style=MUTED,
    )
    console.print()


# ── Tool Execution Display ──────────────────────────────────────────────────


def display_tool_start(tool_name: str, tool_args: dict[str, Any]) -> None:
    """Show a tool invocation start indicator."""
    display_name, color = _TOOL_DISPLAY.get(tool_name, (tool_name, "cyan"))

    # Format args concisely
    args_str = ""
    if tool_args:
        parts = []
        for k, v in tool_args.items():
            if v and v != "" and v != 0:
                parts.append(f"{k}={v}")
        if parts:
            args_str = f" ({', '.join(parts)})"

    console.print(
        f"  [{color}]{display_name}[/{color}]{args_str}",
        style=DIM,
    )


def display_tool_end(tool_name: str, result: str) -> None:
    """Show a tool result in a styled panel."""
    display_name, color = _TOOL_DISPLAY.get(tool_name, (tool_name, "cyan"))

    # For short results, show inline; for long results, use a panel
    if len(result) < 120 and "\n" not in result:
        console.print(f"  {OK} {result}", highlight=False)
    else:
        console.print(
            Panel(
                Markdown(result),
                title=f"[{color}]{display_name}[/{color}]",
                border_style=color,
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )


# ── Streaming Display ───────────────────────────────────────────────────────


class StreamingDisplay:
    """Manages streaming token output to the terminal.

    Uses direct stdout writes for reliable character-by-character streaming.
    Rich.Live is intentionally avoided because it re-renders the full buffer
    on each update, which conflicts with prompt_toolkit's stdout patching
    and causes duplicate output.
    """

    def __init__(self) -> None:
        self._buffer: list[str] = []
        self._started = False

    def start(self) -> None:
        """Begin streaming display."""
        self._buffer = []
        self._started = True

    def add_token(self, token: str) -> None:
        """Append a streamed token and write directly to stdout."""
        self._buffer.append(token)
        import sys

        sys.stdout.write(token)
        sys.stdout.flush()

    def finish(self) -> str:
        """Finish streaming output.

        Adds a trailing newline after the raw streamed text.
        Does NOT re-render as Markdown — the raw stream is the final
        output.  Re-rendering would duplicate the content since we
        can't erase what was already written to stdout.

        Returns:
            The complete response text.
        """
        import sys

        full_text = "".join(self._buffer)
        self._started = False

        if full_text.strip():
            sys.stdout.write("\n")
            sys.stdout.flush()

        return full_text

    def cancel(self) -> str:
        """Cancel streaming and clean up."""
        import sys

        full_text = "".join(self._buffer)
        self._started = False
        if full_text.strip():
            sys.stdout.write("\n")
            sys.stdout.flush()
            console.print("  (cancelled)", style=DIM)
        return full_text


# ── Error / Info Display ────────────────────────────────────────────────────


def display_chat_error(message: str) -> None:
    """Show an error message."""
    console.print(
        Panel(
            Text(message, style=ERROR),
            border_style=ERROR_BORDER,
            box=box.ROUNDED,
            title="[red]Error[/red]",
            padding=(0, 1),
        )
    )


def display_chat_info(message: str) -> None:
    """Show an informational message."""
    console.print(f"  {message}", style=DIM)


def display_mode_change(new_mode: str) -> None:
    """Show mode change confirmation."""
    style = SUCCESS if new_mode == "paper" else ERROR
    console.print(f"\n  Mode switched to [{style}]{new_mode.upper()}[/{style}]\n")


def display_history_summary(messages: list) -> None:
    """Show a summary of conversation history."""
    if not messages:
        console.print("  No conversation history.", style=DIM)
        return

    console.print(f"\n  Conversation: {len(messages)} messages\n", style=BRAND_DIM)
    for msg in messages[-10:]:  # Show last 10
        role = "You" if msg.type == "human" else "AI"
        style = "bold white" if role == "You" else BRAND_DIM
        content = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        content = content.replace("\n", " ")
        console.print(f"  [{style}]{role}:[/{style}] {content}", highlight=False)
    console.print()

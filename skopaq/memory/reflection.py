"""Post-trade reflection generator and memory retrieval.

Generates natural-language lessons from completed trades and provides
retrieval functions for injecting past lessons into agent prompts.

The reflection loop:
    trade closes → generate_reflection() → store in Supabase
    next session → load_recent_lessons() → inject into system prompt
    chat query  → recall() → BM25 search over past reflections
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from supabase import Client

logger = logging.getLogger(__name__)

# Supabase table for reflections (separate from agent_memories)
_TABLE = "trade_reflections"

REFLECTION_PROMPT = """\
You are a trading journal analyst. A trade has just been completed.
Analyze the outcome and generate a concise lesson for future trades.

## Trade Details
- Symbol: {symbol}
- Side: {side}
- Entry Price: {entry_price}
- Exit Price: {exit_price}
- P&L: {pnl} INR ({pnl_pct}%)
- Outcome: {outcome}
- Entry Reason: {entry_reason}
- Exit Reason: {exit_reason}
- Duration: {duration}

## Instructions
Write a 2-3 sentence reflection covering:
1. What was the entry signal and was it correct?
2. What market conditions contributed to the outcome?
3. One specific, actionable lesson for future trades.

Be specific and concrete. Reference the actual signal type and market conditions.
Do NOT use generic advice like "always use stop losses" — focus on what's unique to THIS trade.
"""


async def generate_reflection(
    llm: BaseChatModel,
    *,
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    pnl: float,
    pnl_pct: float,
    entry_reason: str = "",
    exit_reason: str = "",
    duration: str = "",
) -> str:
    """Generate a natural-language reflection on a completed trade.

    Args:
        llm: LLM to use for reflection generation.
        symbol: Stock symbol.
        side: BUY or SELL.
        entry_price: Entry fill price.
        exit_price: Exit fill price.
        pnl: Realized P&L in INR.
        pnl_pct: P&L as percentage.
        entry_reason: Why the entry signal was generated.
        exit_reason: Why the position was closed.
        duration: How long the position was held.

    Returns:
        A 2-3 sentence reflection string.
    """
    from langchain_core.messages import HumanMessage

    outcome = "PROFIT" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"

    prompt = REFLECTION_PROMPT.format(
        symbol=symbol,
        side=side,
        entry_price=f"₹{entry_price:,.2f}" if entry_price else "N/A",
        exit_price=f"₹{exit_price:,.2f}" if exit_price else "N/A",
        pnl=f"₹{pnl:,.2f}",
        pnl_pct=f"{pnl_pct:+.2f}",
        outcome=outcome,
        entry_reason=entry_reason[:300] if entry_reason else "N/A",
        exit_reason=exit_reason[:200] if exit_reason else "N/A",
        duration=duration or "N/A",
    )

    try:
        from skopaq.llm import extract_text

        response = await llm.ainvoke([HumanMessage(content=prompt)])
        return extract_text(response.content)
    except Exception:
        logger.warning("Reflection generation failed", exc_info=True)
        return (
            f"{outcome} on {symbol}: entry@{entry_price}, exit@{exit_price}, "
            f"P&L={pnl:+.2f} ({pnl_pct:+.2f}%)"
        )


def store_reflection(
    client: Client,
    *,
    symbol: str,
    reflection: str,
    pnl: float,
    pnl_pct: float,
    trade_date: str = "",
) -> None:
    """Store a trade reflection in Supabase.

    Creates the table row if it doesn't exist. Silently degrades if
    Supabase is unavailable.
    """
    try:
        data = {
            "symbol": symbol,
            "reflection": reflection,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "trade_date": trade_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        client.table(_TABLE).insert(data).execute()
        logger.info("Reflection stored for %s", symbol)
    except Exception:
        logger.warning("Failed to store reflection for %s", symbol, exc_info=True)


def load_recent_lessons(client: Client, limit: int = 10) -> list[dict]:
    """Load recent trade reflections from Supabase.

    Returns a list of dicts with keys: symbol, reflection, pnl, trade_date.
    """
    try:
        result = (
            client.table(_TABLE)
            .select("symbol, reflection, pnl, pnl_pct, trade_date")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.debug("Failed to load reflections: %s", exc)
        return []


def format_lessons_for_prompt(lessons: list[dict]) -> str:
    """Format lessons into a string suitable for the agent system prompt."""
    if not lessons:
        return ""

    lines = []
    for lesson in lessons:
        symbol = lesson.get("symbol", "?")
        date = lesson.get("trade_date", "?")
        reflection = lesson.get("reflection", "")
        pnl = lesson.get("pnl", 0)
        outcome = "PROFIT" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"
        lines.append(f"- **{symbol}** ({date}, {outcome}): {reflection}")

    return "\n".join(lines)


def recall(client: Client, query: str, limit: int = 5) -> list[dict]:
    """Search reflections by keyword (text search via Supabase ilike).

    For a proper implementation, use BM25 or vector search. This is a
    simple substring match as a starting point.
    """
    try:
        result = (
            client.table(_TABLE)
            .select("symbol, reflection, pnl, pnl_pct, trade_date")
            .ilike("reflection", f"%{query}%")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception:
        logger.warning("Recall search failed for '%s'", query, exc_info=True)
        return []

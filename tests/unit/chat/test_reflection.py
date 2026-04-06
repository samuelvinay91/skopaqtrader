"""Tests for memory reflection generation and retrieval."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skopaq.memory.reflection import (
    format_lessons_for_prompt,
    generate_reflection,
)


def test_format_lessons_empty():
    assert format_lessons_for_prompt([]) == ""


def test_format_lessons_single():
    lessons = [
        {
            "symbol": "RELIANCE",
            "trade_date": "2026-03-15",
            "reflection": "Momentum + fundamentals = higher confidence",
            "pnl": 1500.0,
        }
    ]
    result = format_lessons_for_prompt(lessons)
    assert "RELIANCE" in result
    assert "2026-03-15" in result
    assert "PROFIT" in result
    assert "Momentum" in result


def test_format_lessons_loss():
    lessons = [
        {
            "symbol": "TCS",
            "trade_date": "2026-03-20",
            "reflection": "Volume confirmation was missing",
            "pnl": -500.0,
        }
    ]
    result = format_lessons_for_prompt(lessons)
    assert "LOSS" in result
    assert "TCS" in result


def test_format_lessons_multiple():
    lessons = [
        {"symbol": "RELIANCE", "trade_date": "2026-03-15", "reflection": "Good", "pnl": 100},
        {"symbol": "TCS", "trade_date": "2026-03-16", "reflection": "Bad", "pnl": -50},
    ]
    result = format_lessons_for_prompt(lessons)
    assert result.count("- **") == 2


@pytest.mark.asyncio
async def test_generate_reflection():
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = MagicMock(
        content="The BUY signal was correct because momentum aligned with volume."
    )

    result = await generate_reflection(
        mock_llm,
        symbol="RELIANCE",
        side="BUY",
        entry_price=2500.0,
        exit_price=2600.0,
        pnl=1000.0,
        pnl_pct=4.0,
        entry_reason="Strong momentum",
        exit_reason="Trailing stop",
        duration="2 hours",
    )
    assert "BUY signal was correct" in result
    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_generate_reflection_fallback_on_error():
    mock_llm = AsyncMock()
    mock_llm.ainvoke.side_effect = Exception("LLM timeout")

    result = await generate_reflection(
        mock_llm,
        symbol="TCS",
        side="BUY",
        entry_price=3500.0,
        exit_price=3400.0,
        pnl=-100.0,
        pnl_pct=-2.86,
    )
    # Should return a fallback summary, not raise
    assert "LOSS" in result
    assert "TCS" in result

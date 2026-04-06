"""Tests for the REPL input handling and slash commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skopaq.chat.repl import _handle_slash_command
from skopaq.chat.session import ChatSession


@pytest.fixture
def session():
    config = MagicMock()
    config.trading_mode = "paper"
    config.asset_class = "equity"
    s = ChatSession(config)
    return s


@pytest.mark.asyncio
async def test_slash_exit(session):
    result = await _handle_slash_command("/exit", session)
    assert result is True


@pytest.mark.asyncio
async def test_slash_quit(session):
    result = await _handle_slash_command("/quit", session)
    assert result is True


@pytest.mark.asyncio
async def test_slash_help(session):
    result = await _handle_slash_command("/help", session)
    assert result is False


@pytest.mark.asyncio
async def test_slash_clear(session):
    session.add_user_message("msg1")
    session.add_ai_message("reply")
    assert len(session.messages) == 2

    result = await _handle_slash_command("/clear", session)
    assert result is False
    assert len(session.messages) == 0


@pytest.mark.asyncio
async def test_slash_history(session):
    session.add_user_message("msg1")
    result = await _handle_slash_command("/history", session)
    assert result is False


@pytest.mark.asyncio
async def test_slash_mode_show(session):
    result = await _handle_slash_command("/mode", session)
    assert result is False


@pytest.mark.asyncio
async def test_slash_mode_switch_paper(session):
    session.config.trading_mode = "live"
    result = await _handle_slash_command("/mode paper", session)
    assert result is False
    assert session.config.trading_mode == "paper"


@pytest.mark.asyncio
async def test_slash_mode_switch_live_denied(session):
    """Live switch should be denied when confirmation fails."""
    with patch("skopaq.chat.repl._prompt_confirm", new_callable=AsyncMock) as mock_confirm:
        mock_confirm.return_value = False
        result = await _handle_slash_command("/mode live", session)
        assert result is False
        assert session.config.trading_mode == "paper"  # not changed


@pytest.mark.asyncio
async def test_slash_unknown_command(session):
    result = await _handle_slash_command("/foobar", session)
    assert result is False


@pytest.mark.asyncio
@patch("skopaq.chat.repl._run_slash_tool", new_callable=AsyncMock)
async def test_slash_scan(mock_run, session):
    result = await _handle_slash_command("/scan", session)
    assert result is False
    mock_run.assert_called_once_with(session, "scan_market", max_candidates=5)


@pytest.mark.asyncio
@patch("skopaq.chat.repl._run_slash_tool", new_callable=AsyncMock)
async def test_slash_scan_with_count(mock_run, session):
    result = await _handle_slash_command("/scan 10", session)
    assert result is False
    mock_run.assert_called_once_with(session, "scan_market", max_candidates=10)


@pytest.mark.asyncio
@patch("skopaq.chat.repl._run_slash_tool", new_callable=AsyncMock)
async def test_slash_portfolio(mock_run, session):
    result = await _handle_slash_command("/portfolio", session)
    assert result is False
    mock_run.assert_called_once_with(session, "get_portfolio")


@pytest.mark.asyncio
@patch("skopaq.chat.repl._run_slash_tool", new_callable=AsyncMock)
async def test_slash_positions_alias(mock_run, session):
    result = await _handle_slash_command("/positions", session)
    assert result is False
    mock_run.assert_called_once_with(session, "get_portfolio")


@pytest.mark.asyncio
@patch("skopaq.chat.repl._run_slash_tool", new_callable=AsyncMock)
async def test_slash_orders(mock_run, session):
    result = await _handle_slash_command("/orders", session)
    assert result is False
    mock_run.assert_called_once_with(session, "get_orders")


@pytest.mark.asyncio
@patch("skopaq.chat.repl._run_slash_tool", new_callable=AsyncMock)
async def test_slash_status(mock_run, session):
    result = await _handle_slash_command("/status", session)
    assert result is False
    mock_run.assert_called_once_with(session, "check_status")


@pytest.mark.asyncio
@patch("skopaq.chat.repl._run_slash_tool", new_callable=AsyncMock)
async def test_slash_quote(mock_run, session):
    result = await _handle_slash_command("/quote RELIANCE", session)
    assert result is False
    mock_run.assert_called_once_with(session, "get_quote", symbol="RELIANCE")


@pytest.mark.asyncio
async def test_slash_quote_without_symbol(session):
    """Should show usage hint, not call tool."""
    result = await _handle_slash_command("/quote", session)
    assert result is False

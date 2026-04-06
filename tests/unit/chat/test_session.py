"""Tests for ChatSession and Infrastructure."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from skopaq.chat.session import ChatSession, Infrastructure


@pytest.fixture
def mock_config():
    cfg = MagicMock()
    cfg.trading_mode = "paper"
    cfg.asset_class = "equity"
    cfg.initial_paper_capital = 100_000
    cfg.max_sector_concentration_pct = 0.40
    cfg.position_sizing_enabled = False
    cfg.risk_per_trade_pct = 0.01
    cfg.atr_multiplier = 2.0
    cfg.atr_period = 14
    cfg.regime_detection_enabled = False
    cfg.langcache_enabled = False
    cfg.google_api_key = MagicMock()
    cfg.google_api_key.get_secret_value.return_value = "test"
    cfg.anthropic_api_key = MagicMock()
    cfg.anthropic_api_key.get_secret_value.return_value = ""
    cfg.perplexity_api_key = MagicMock()
    cfg.perplexity_api_key.get_secret_value.return_value = ""
    cfg.xai_api_key = MagicMock()
    cfg.xai_api_key.get_secret_value.return_value = ""
    cfg.openrouter_api_key = MagicMock()
    cfg.openrouter_api_key.get_secret_value.return_value = ""
    cfg.selected_analysts = "market,social"
    cfg.reflection_enabled = False
    cfg.supabase_url = ""
    cfg.supabase_service_key = MagicMock()
    cfg.supabase_service_key.get_secret_value.return_value = ""
    cfg.max_debate_rounds = 1
    cfg.max_risk_discuss_rounds = 1
    cfg.google_thinking_level = ""
    cfg.binance_base_url = "https://api.binance.com"
    cfg.crypto_quote_currency = "USDT"
    cfg.langcache_threshold = 0.90
    cfg.langcache_api_key = MagicMock()
    cfg.langcache_api_key.get_secret_value.return_value = ""
    cfg.langcache_server_url = ""
    cfg.langcache_cache_id = ""
    return cfg


def test_session_creation(mock_config):
    session = ChatSession(mock_config)
    assert session.config is mock_config
    assert session.messages == []
    assert session.infra is None
    assert session.agent is None
    assert session.checkpointer is None
    assert session.id  # non-empty UUID


def test_thread_config(mock_config):
    session = ChatSession(mock_config)
    cfg = session.thread_config
    assert "configurable" in cfg
    assert "thread_id" in cfg["configurable"]
    assert cfg["configurable"]["thread_id"] == session.id


def test_add_user_message(mock_config):
    session = ChatSession(mock_config)
    session.add_user_message("hello")
    assert len(session.messages) == 1
    assert session.messages[0].type == "human"
    assert session.messages[0].content == "hello"


def test_add_ai_message(mock_config):
    session = ChatSession(mock_config)
    session.add_ai_message("I can help with that")
    assert len(session.messages) == 1
    assert session.messages[0].type == "ai"


def test_get_history_returns_copy(mock_config):
    session = ChatSession(mock_config)
    session.add_user_message("msg1")
    history = session.get_history()
    assert len(history) == 1
    # Modifying the returned list should not affect session
    history.clear()
    assert len(session.messages) == 1


def test_clear_resets_history(mock_config):
    session = ChatSession(mock_config)
    session.add_user_message("msg1")
    session.add_ai_message("reply")
    session.add_user_message("msg2")
    assert len(session.messages) == 3

    session.clear()
    assert len(session.messages) == 0


@patch("skopaq.chat.session.build_infrastructure")
def test_ensure_infra_lazily_initialised(mock_build, mock_config):
    mock_infra = MagicMock(spec=Infrastructure)
    mock_build.return_value = mock_infra

    session = ChatSession(mock_config)
    assert session.infra is None

    result = session.ensure_infra()
    assert result is mock_infra
    mock_build.assert_called_once_with(mock_config)

    # Second call should not rebuild
    result2 = session.ensure_infra()
    assert result2 is mock_infra
    assert mock_build.call_count == 1

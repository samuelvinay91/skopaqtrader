"""Tests for chat agent creation and configuration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from skopaq.chat.agent import GATED_TOOLS, SYSTEM_PROMPT_TEMPLATE, create_chat_agent
from skopaq.chat.session import Infrastructure


@pytest.fixture
def mock_infra():
    infra = MagicMock()
    infra.config.trading_mode = "paper"
    infra.config.asset_class = "equity"
    infra.llm_map = {
        "chat_brain": MagicMock(),
        "research_manager": MagicMock(),
        "_default": MagicMock(),
    }
    infra.upstream_config = {}
    return infra


def test_system_prompt_contains_mode():
    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        trading_mode="paper",
        asset_class="equity",
        current_date="2026-04-06",
        memory_section="",
    )
    assert "paper" in prompt.lower()
    assert "equity" in prompt.lower()
    assert "2026-04-06" in prompt


def test_system_prompt_contains_rules():
    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        trading_mode="live",
        asset_class="crypto",
        current_date="2026-04-06",
        memory_section="",
    )
    assert "Paper trading is the default" in prompt
    assert "SafetyChecker" in prompt
    assert "live" in prompt


def test_system_prompt_includes_memory():
    memory = "\n## Past Trade Lessons\n- RELIANCE: BUY was correct\n"
    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        trading_mode="paper",
        asset_class="equity",
        current_date="2026-04-06",
        memory_section=memory,
    )
    assert "Past Trade Lessons" in prompt
    assert "RELIANCE" in prompt


def test_gated_tools_contains_trade():
    assert "trade_stock" in GATED_TOOLS


@patch("skopaq.chat.agent.create_react_agent")
def test_create_agent_returns_tuple(mock_create, mock_infra):
    mock_agent = MagicMock()
    mock_create.return_value = mock_agent

    result = create_chat_agent(mock_infra)

    assert isinstance(result, tuple)
    assert len(result) == 2
    agent, checkpointer = result
    assert agent is mock_agent


@patch("skopaq.chat.agent.create_react_agent")
def test_create_agent_binds_tools(mock_create, mock_infra):
    mock_create.return_value = MagicMock()

    create_chat_agent(mock_infra)
    mock_create.assert_called_once()

    call_kwargs = mock_create.call_args
    tools = call_kwargs[1].get("tools") or call_kwargs[0][1]
    assert len(tools) == 12


@patch("skopaq.chat.agent.create_react_agent")
def test_create_agent_has_checkpointer(mock_create, mock_infra):
    mock_create.return_value = MagicMock()

    create_chat_agent(mock_infra)

    call_kwargs = mock_create.call_args[1]
    assert "checkpointer" in call_kwargs
    assert call_kwargs["checkpointer"] is not None


@patch("skopaq.chat.agent.create_react_agent")
def test_create_agent_has_interrupt_before(mock_create, mock_infra):
    mock_create.return_value = MagicMock()

    create_chat_agent(mock_infra)

    call_kwargs = mock_create.call_args[1]
    assert "interrupt_before" in call_kwargs
    assert call_kwargs["interrupt_before"] == ["tools"]


@patch("skopaq.chat.agent.create_react_agent")
def test_create_agent_uses_chat_brain(mock_create, mock_infra):
    mock_create.return_value = MagicMock()

    create_chat_agent(mock_infra)

    call_kwargs = mock_create.call_args
    model = call_kwargs[1].get("model") or call_kwargs[0][0]
    assert model is mock_infra.llm_map["chat_brain"]


@patch("skopaq.chat.agent.create_react_agent")
def test_create_agent_falls_back_to_research_manager(mock_create):
    infra = MagicMock()
    infra.config.trading_mode = "paper"
    infra.config.asset_class = "equity"
    infra.llm_map = {
        "research_manager": MagicMock(),
        "_default": MagicMock(),
    }
    infra.upstream_config = {}

    mock_create.return_value = MagicMock()
    create_chat_agent(infra)

    call_kwargs = mock_create.call_args
    model = call_kwargs[1].get("model") or call_kwargs[0][0]
    assert model is infra.llm_map["research_manager"]


@patch("skopaq.chat.agent.create_react_agent")
def test_create_agent_falls_back_to_default(mock_create):
    infra = MagicMock()
    infra.config.trading_mode = "paper"
    infra.config.asset_class = "equity"
    infra.llm_map = {"_default": MagicMock()}
    infra.upstream_config = {}

    mock_create.return_value = MagicMock()
    create_chat_agent(infra)

    call_kwargs = mock_create.call_args
    model = call_kwargs[1].get("model") or call_kwargs[0][0]
    assert model is infra.llm_map["_default"]


def test_create_agent_raises_without_llm():
    infra = MagicMock()
    infra.config.trading_mode = "paper"
    infra.config.asset_class = "equity"
    infra.llm_map = {}
    infra.upstream_config = {}

    with pytest.raises(RuntimeError, match="No LLM available"):
        create_chat_agent(infra)

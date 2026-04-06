"""LangGraph ReAct agent for the interactive trading chatbot.

Uses ``create_react_agent`` with Claude Opus as the brain and 10+ trading
tools.  The agent decides which tools to call based on natural language
input, maintains conversation history, and supports streaming.

**Checkpointing** — ``MemorySaver`` persists agent state after every step.
If the process crashes mid-analysis, the session can resume from the last
checkpoint.  Thread IDs isolate state per conversation.

**Human-in-the-Loop** — The ``trade_stock`` tool is gated by
``interrupt_before`` so the agent pauses before executing trades.  The
REPL detects the interrupt, shows the pending trade, and prompts for
user confirmation before resuming.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from skopaq.chat.session import Infrastructure
from skopaq.chat.tools import get_all_tools, init_tools

logger = logging.getLogger(__name__)

# Names of tools that require user confirmation before execution.
# The agent will pause (interrupt) before calling these.
GATED_TOOLS = {"trade_stock"}

SYSTEM_PROMPT_TEMPLATE = """\
You are **SkopaqTrader**, an AI trading assistant for Indian equities and crypto.
You help users analyze stocks, manage their portfolio, execute trades, scan \
the market for opportunities, and monitor positions.

## Rules
- **Paper trading is the default.** Never execute live trades unless the user \
explicitly switches to live mode.
- Always show confidence scores and reasoning when presenting trade signals.
- When the user asks to trade, run analyze_stock first to show the signal, \
then ask for confirmation before calling trade_stock.
- Format currency in INR (₹) using Indian number system (lakhs, crores).
- All trades go through the SafetyChecker. You cannot bypass safety rules.
- Be concise but informative. Use bullet points for multiple data points.
- If a tool call fails, explain the error and suggest alternatives.
- For long-running operations (analyze, trade, scan), warn the user it will \
take a few minutes.
{memory_section}
## Current State
- Trading Mode: {trading_mode}
- Asset Class: {asset_class}
- Date: {current_date}

## Available Actions
You can analyze stocks, execute trades, scan the market for candidates, \
check portfolio positions/funds, get real-time quotes, view today's orders, \
check system status, compute position sizes, validate safety rules, \
fetch historical market data, recall lessons from past trades, and view \
trade history.
"""


def create_chat_agent(infra: Infrastructure, memory_context: str = ""):
    """Create and return a compiled LangGraph ReAct agent.

    The agent uses ``MemorySaver`` for checkpointing and ``interrupt_before``
    on the tools node to pause before trade execution for user confirmation.

    Args:
        infra: Shared infrastructure (provides config and LLM map).
        memory_context: Optional past-trade lessons to inject into system prompt.

    Returns:
        A tuple of ``(agent, checkpointer)`` — the compiled ``StateGraph``
        and its ``MemorySaver`` for state persistence.
    """
    # Bind infrastructure to tools
    init_tools(infra)
    tools = get_all_tools()

    # Get the chat brain LLM (Claude Opus, falls back to Gemini Flash)
    brain = infra.llm_map.get("chat_brain") or infra.llm_map.get(
        "research_manager"
    ) or infra.llm_map.get("_default")

    if brain is None:
        raise RuntimeError(
            "No LLM available for chat brain — check API key configuration"
        )

    # Format system prompt with current state
    memory_section = ""
    if memory_context:
        memory_section = f"\n## Past Trade Lessons\n{memory_context}\n"

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        trading_mode=infra.config.trading_mode,
        asset_class=infra.config.asset_class,
        current_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        memory_section=memory_section,
    )

    # Checkpointer — persists agent state after every step.
    # MemorySaver is in-process (no external DB), perfect for desktop.
    checkpointer = MemorySaver()

    # Create the ReAct agent with checkpointing + human-in-the-loop
    agent = create_react_agent(
        model=brain,
        tools=tools,
        prompt=system_prompt,
        checkpointer=checkpointer,
        interrupt_before=["tools"],
    )

    logger.info(
        "Chat agent created: brain=%s, tools=%d, checkpointed=True, "
        "gated_tools=%s",
        getattr(brain, "model_name", getattr(brain, "model", "unknown")),
        len(tools),
        GATED_TOOLS,
    )

    return agent, checkpointer

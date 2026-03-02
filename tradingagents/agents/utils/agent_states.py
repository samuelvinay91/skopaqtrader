from typing import Annotated, Sequence
from datetime import date, timedelta, datetime
from typing_extensions import TypedDict, Optional
from langchain_openai import ChatOpenAI
from tradingagents.agents import *
from langgraph.prebuilt import ToolNode
from langgraph.graph import END, StateGraph, START, MessagesState


# ── Reducers for parallel fan-out/fan-in ──────────────────────────
# LangGraph's default LastValue channel throws when multiple parallel
# branches converge (fan-in). Custom reducers let the framework merge
# state from parallel analyst branches safely.


def _last_str(a: str, b: str) -> str:
    """Reducer: keep latest non-empty string value."""
    return b if b else a


def _last_invest_state(a, b):
    """Reducer: keep the InvestDebateState with more progress (higher count)."""
    if isinstance(b, dict) and b.get("count", 0) >= (a.get("count", 0) if isinstance(a, dict) else 0):
        return b
    return a


def _last_risk_state(a, b):
    """Reducer: keep the RiskDebateState with more progress (higher count)."""
    if isinstance(b, dict) and b.get("count", 0) >= (a.get("count", 0) if isinstance(a, dict) else 0):
        return b
    return a


# Researcher team state
class InvestDebateState(TypedDict):
    bull_history: Annotated[
        str, "Bullish Conversation history"
    ]  # Bullish Conversation history
    bear_history: Annotated[
        str, "Bearish Conversation history"
    ]  # Bullish Conversation history
    history: Annotated[str, "Conversation history"]  # Conversation history
    current_response: Annotated[str, "Latest response"]  # Last response
    judge_decision: Annotated[str, "Final judge decision"]  # Last response
    count: Annotated[int, "Length of the current conversation"]  # Conversation length


# Risk management team state
class RiskDebateState(TypedDict):
    aggressive_history: Annotated[
        str, "Aggressive Agent's Conversation history"
    ]  # Conversation history
    conservative_history: Annotated[
        str, "Conservative Agent's Conversation history"
    ]  # Conversation history
    neutral_history: Annotated[
        str, "Neutral Agent's Conversation history"
    ]  # Conversation history
    history: Annotated[str, "Conversation history"]  # Conversation history
    latest_speaker: Annotated[str, "Analyst that spoke last"]
    current_aggressive_response: Annotated[
        str, "Latest response by the aggressive analyst"
    ]  # Last response
    current_conservative_response: Annotated[
        str, "Latest response by the conservative analyst"
    ]  # Last response
    current_neutral_response: Annotated[
        str, "Latest response by the neutral analyst"
    ]  # Last response
    judge_decision: Annotated[str, "Judge's decision"]
    count: Annotated[int, "Length of the current conversation"]  # Conversation length


class AgentState(MessagesState):
    company_of_interest: Annotated[str, _last_str]
    trade_date: Annotated[str, _last_str]

    sender: Annotated[str, _last_str]

    # research step — each analyst writes its own report during parallel fan-out
    market_report: Annotated[str, _last_str]
    sentiment_report: Annotated[str, _last_str]
    news_report: Annotated[str, _last_str]
    fundamentals_report: Annotated[str, _last_str]

    # researcher team discussion step
    investment_debate_state: Annotated[InvestDebateState, _last_invest_state]
    investment_plan: Annotated[str, _last_str]

    trader_investment_plan: Annotated[str, _last_str]

    # risk management team discussion step
    risk_debate_state: Annotated[RiskDebateState, _last_risk_state]
    final_trade_decision: Annotated[str, _last_str]

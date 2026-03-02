"""Wrapper around upstream TradingAgentsGraph + Skopaq execution pipeline.

This is the main entry point for running an analysis-and-trade cycle.
It calls the upstream ``propagate()`` as a black box, then routes the
decision through safety checks and order execution.

Zero modifications to upstream ``tradingagents/`` code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from skopaq.broker.models import Exchange, ExecutionResult, TradingSignal
from skopaq.execution.executor import Executor

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Complete result of an analyze-and-execute cycle."""

    symbol: str
    trade_date: str
    signal: Optional[TradingSignal] = None
    execution: Optional[ExecutionResult] = None
    agent_state: dict[str, Any] = field(default_factory=dict)
    raw_decision: str = ""
    error: Optional[str] = None
    duration_seconds: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SkopaqTradingGraph:
    """Wraps upstream TradingAgentsGraph with Skopaq execution.

    Pipeline::

        propagate(symbol, date)  →  parse signal  →  executor.execute_signal()

    When a ``MemoryStore`` is provided, memories are loaded from Supabase
    before the first ``propagate()`` call, and saved back after reflection.

    Args:
        upstream_config: Config dict for TradingAgentsGraph (LLM keys, etc).
        executor: The Skopaq execution pipeline (safety → route → fill).
        selected_analysts: Which upstream analysts to enable.
        debug: Enable upstream debug/tracing mode.
        memory_store: Optional persistence layer for agent memories.
    """

    def __init__(
        self,
        upstream_config: dict[str, Any],
        executor: Executor,
        selected_analysts: Optional[list[str]] = None,
        debug: bool = False,
        memory_store: Optional[Any] = None,
    ) -> None:
        self._executor = executor
        self._upstream_config = upstream_config
        self._selected_analysts = selected_analysts or [
            "market", "social", "news", "fundamentals",
        ]
        self._debug = debug
        self._memory_store = memory_store
        self._graph: Any = None  # Lazy-init upstream graph

    def _ensure_graph(self) -> Any:
        """Lazy-import and initialise the upstream TradingAgentsGraph."""
        if self._graph is not None:
            return self._graph

        # Bridge SKOPAQ_ env vars → standard LLM env vars before upstream init
        from skopaq.llm.env_bridge import bridge_env_vars
        bridge_env_vars()

        # Import upstream at runtime to avoid import-time side effects
        from tradingagents.graph import TradingAgentsGraph

        self._graph = TradingAgentsGraph(
            selected_analysts=self._selected_analysts,
            debug=self._debug,
            config=self._upstream_config,
        )
        logger.info(
            "Upstream TradingAgentsGraph initialised (analysts=%s, debug=%s)",
            self._selected_analysts, self._debug,
        )

        # Restore persisted memories into the upstream graph's memory objects
        if self._memory_store is not None:
            try:
                loaded = self._memory_store.load(self._graph)
                logger.info("Agent memories loaded from Supabase (%d entries)", loaded)
            except Exception:
                logger.warning("Memory load failed — agents will start with empty memory", exc_info=True)

        return self._graph

    async def analyze(self, symbol: str, trade_date: str) -> AnalysisResult:
        """Run upstream analysis without executing a trade.

        Useful for getting the agent's recommendation without placing an order.
        """
        import time

        start = time.monotonic()
        try:
            graph = self._ensure_graph()
            state, decision = graph.propagate(symbol, trade_date)

            signal = self._parse_signal(symbol, decision, state)
            duration = time.monotonic() - start

            return AnalysisResult(
                symbol=symbol,
                trade_date=trade_date,
                signal=signal,
                agent_state=state if isinstance(state, dict) else {},
                raw_decision=str(decision),
                duration_seconds=round(duration, 2),
            )
        except Exception as exc:
            duration = time.monotonic() - start
            logger.exception("Analysis failed for %s", symbol)
            return AnalysisResult(
                symbol=symbol,
                trade_date=trade_date,
                error=str(exc),
                duration_seconds=round(duration, 2),
            )

    async def analyze_and_execute(
        self,
        symbol: str,
        trade_date: str,
        regime_scale: float = 1.0,
        calendar_scale: float = 1.0,
    ) -> AnalysisResult:
        """Run upstream analysis and execute the resulting signal.

        Full pipeline:
            1. ``upstream.propagate(symbol, date)``  — get agent decision
            2. Parse decision into a ``TradingSignal``
            3. ``executor.execute_signal(signal)``  — safety check → route → fill

        Args:
            symbol: Stock symbol to analyze and trade.
            trade_date: Trading date (YYYY-MM-DD).
            regime_scale: Market regime position multiplier (0.0–1.2).
            calendar_scale: Event calendar position multiplier (0.0–1.0).
        """
        result = await self.analyze(symbol, trade_date)

        if result.error:
            return result

        if result.signal is None or result.signal.action == "HOLD":
            logger.info("Signal is HOLD for %s — no execution", symbol)
            return result

        # Execute the signal through the full pipeline
        execution = await self._executor.execute_signal(
            result.signal,
            trade_date=trade_date,
            regime_scale=regime_scale,
            calendar_scale=calendar_scale,
        )
        result.execution = execution

        logger.info(
            "Cycle complete: %s %s → %s (success=%s, mode=%s)",
            result.signal.action, symbol, execution.mode,
            execution.success, execution.mode,
        )
        return result

    def reflect(self, returns_losses: Any) -> None:
        """Invoke upstream reflection to update agent memories.

        Called after a position close (SELL) to let agents learn from the
        realized P&L.  After the LLM-powered reflection writes lessons into
        the in-memory BM25 stores, we persist them to Supabase so they
        survive across sessions.
        """
        graph = self._ensure_graph()
        graph.reflect_and_remember(returns_losses)
        logger.info("Upstream reflection complete")

        # Persist updated memories to Supabase
        if self._memory_store is not None:
            try:
                saved = self._memory_store.save(self._graph)
                logger.info("Agent memories saved to Supabase (%d entries)", saved)
            except Exception:
                logger.warning("Memory save failed — lessons will be lost on exit", exc_info=True)

    # ── Signal parsing ───────────────────────────────────────────────────

    @staticmethod
    def _parse_signal(
        symbol: str,
        decision: Any,
        state: Any,
    ) -> Optional[TradingSignal]:
        """Convert upstream decision into a typed TradingSignal.

        The upstream ``propagate()`` returns a (state, decision) tuple where
        ``decision`` is a processed signal string like "BUY" / "SELL" / "HOLD",
        and ``state`` is a dict with all intermediate analysis.
        """
        if decision is None:
            return None

        decision_str = str(decision).strip().upper()

        # Extract action
        if "BUY" in decision_str:
            action = "BUY"
        elif "SELL" in decision_str:
            action = "SELL"
        else:
            action = "HOLD"

        # Try to extract confidence from state
        confidence = 50
        if isinstance(state, dict):
            # The risk management node may include a confidence indicator
            risk_state = state.get("risk_debate_state", {})
            if isinstance(risk_state, dict):
                confidence = _extract_confidence(risk_state)

        return TradingSignal(
            symbol=symbol,
            exchange=Exchange.NSE,
            action=action,
            confidence=confidence,
            reasoning=decision_str[:500],
            agent_state=state if isinstance(state, dict) else {},
        )


def _extract_confidence(risk_state: dict[str, Any]) -> int:
    """Attempt to extract a confidence score from the risk debate state.

    Falls back to 50 if no clear signal is found.
    """
    # Check for explicit confidence field
    for key in ("confidence", "score", "certainty"):
        if key in risk_state:
            try:
                val = int(float(risk_state[key]))
                return max(0, min(100, val))
            except (ValueError, TypeError):
                pass

    # Check consensus — if all risk debaters agree, higher confidence
    messages = risk_state.get("messages", [])
    if isinstance(messages, list) and len(messages) >= 3:
        # More messages = more debate = less consensus = lower confidence
        return max(30, 80 - len(messages) * 5)

    return 50

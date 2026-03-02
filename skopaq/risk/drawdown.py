"""Persistent drawdown tracking across process restarts.

Solves a critical safety gap: SafetyChecker._day_pnl is in-memory only.
If the process restarts mid-day, circuit breakers reset to zero — potentially
allowing trades that should be blocked after a 3% daily loss.

DrawdownTracker uses Supabase ``daily_snapshots`` to persist P&L state.
On init it loads today's snapshot; after each trade it updates the snapshot.
This means circuit breakers survive restarts.

Usage::

    tracker = DrawdownTracker(supabase_client)
    state = tracker.restore_state()       # Load today's snapshot
    safety_checker._day_pnl = state["day_pnl"]  # Restore state

    # After a trade closes:
    tracker.record_pnl(pnl_amount=500.0)  # Increments and persists
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)


class DrawdownTracker:
    """Tracks P&L across sessions via Supabase daily snapshots.

    Args:
        supabase_client: Supabase client instance.
        table_name: Name of the snapshots table (default: "daily_snapshots").
    """

    def __init__(
        self,
        supabase_client,
        table_name: str = "daily_snapshots",
    ) -> None:
        self._client = supabase_client
        self._table = table_name
        self._day_pnl: float = 0.0
        self._total_trades: int = 0
        self._winning_trades: int = 0
        self._losing_trades: int = 0
        self._today: date = date.today()
        self._snapshot_id: Optional[str] = None

    def restore_state(self) -> dict:
        """Load today's snapshot from Supabase to restore P&L state.

        Returns:
            Dict with day_pnl, total_trades, winning_trades, losing_trades.
            All zeros if no snapshot exists (new day or first run).
        """
        try:
            today_str = self._today.isoformat()
            result = (
                self._client.table(self._table)
                .select("*")
                .eq("date", today_str)
                .execute()
            )

            if result.data:
                row = result.data[0]
                self._day_pnl = float(row.get("day_pnl", 0))
                self._total_trades = int(row.get("total_trades", 0))
                self._winning_trades = int(row.get("winning_trades", 0))
                self._losing_trades = int(row.get("losing_trades", 0))
                self._snapshot_id = row.get("id")

                logger.info(
                    "Restored drawdown state: day_pnl=%.2f, trades=%d (W:%d/L:%d)",
                    self._day_pnl, self._total_trades,
                    self._winning_trades, self._losing_trades,
                )
            else:
                logger.info("No snapshot for %s — starting fresh", today_str)

        except Exception:
            logger.warning(
                "Failed to restore drawdown state — using defaults",
                exc_info=True,
            )

        return {
            "day_pnl": self._day_pnl,
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "losing_trades": self._losing_trades,
        }

    def record_pnl(
        self,
        pnl_amount: float,
        portfolio_value: float = 0.0,
        cash: float = 0.0,
    ) -> None:
        """Record a trade's P&L and persist to Supabase.

        Args:
            pnl_amount: Trade P&L (positive = profit, negative = loss).
            portfolio_value: Current portfolio value for snapshot.
            cash: Current cash balance for snapshot.
        """
        self._day_pnl += pnl_amount
        self._total_trades += 1
        if pnl_amount > 0:
            self._winning_trades += 1
        elif pnl_amount < 0:
            self._losing_trades += 1

        self._persist_snapshot(portfolio_value, cash)

    def _persist_snapshot(self, portfolio_value: float, cash: float) -> None:
        """Upsert today's snapshot to Supabase."""
        try:
            data = {
                "date": self._today.isoformat(),
                "day_pnl": str(self._day_pnl),
                "total_trades": self._total_trades,
                "winning_trades": self._winning_trades,
                "losing_trades": self._losing_trades,
                "portfolio_value": str(portfolio_value) if portfolio_value else "0",
                "cash": str(cash) if cash else "0",
            }

            if self._snapshot_id:
                data["id"] = self._snapshot_id

            result = (
                self._client.table(self._table)
                .upsert(data, on_conflict="date")
                .execute()
            )

            if result.data:
                self._snapshot_id = result.data[0].get("id")
                logger.debug("Persisted drawdown snapshot: day_pnl=%.2f", self._day_pnl)

        except Exception:
            logger.warning(
                "Failed to persist drawdown snapshot — state may be lost on restart",
                exc_info=True,
            )

    @property
    def day_pnl(self) -> float:
        """Current day's P&L."""
        return self._day_pnl

    @property
    def total_trades(self) -> int:
        """Total trades today."""
        return self._total_trades

    @property
    def winning_trades(self) -> int:
        """Winning trades today."""
        return self._winning_trades

    @property
    def losing_trades(self) -> int:
        """Losing trades today."""
        return self._losing_trades

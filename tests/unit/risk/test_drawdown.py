"""Tests for persistent drawdown tracking.

Uses a mock Supabase client to verify restore/persist lifecycle
without network calls.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from skopaq.risk.drawdown import DrawdownTracker


# ── Mock Supabase client ──────────────────────────────────────────────────────


def _mock_supabase(existing_snapshot=None):
    """Create a mock Supabase client that returns the given snapshot."""
    client = MagicMock()
    table = MagicMock()
    client.table.return_value = table

    # Chain for select().eq().execute()
    select_chain = MagicMock()
    table.select.return_value = select_chain
    eq_chain = MagicMock()
    select_chain.eq.return_value = eq_chain

    result = MagicMock()
    result.data = [existing_snapshot] if existing_snapshot else []
    eq_chain.execute.return_value = result

    # Chain for upsert().execute()
    upsert_chain = MagicMock()
    table.upsert.return_value = upsert_chain
    upsert_result = MagicMock()
    upsert_result.data = [{"id": "snap-123"}]
    upsert_chain.execute.return_value = upsert_result

    return client


# ── Restore state tests ───────────────────────────────────────────────────────


class TestRestoreState:
    def test_restore_existing_snapshot(self):
        """Should restore P&L from today's existing snapshot."""
        snapshot = {
            "id": "snap-001",
            "day_pnl": -5000.0,
            "total_trades": 3,
            "winning_trades": 1,
            "losing_trades": 2,
        }
        client = _mock_supabase(existing_snapshot=snapshot)
        tracker = DrawdownTracker(client)

        state = tracker.restore_state()

        assert state["day_pnl"] == -5000.0
        assert state["total_trades"] == 3
        assert state["winning_trades"] == 1
        assert state["losing_trades"] == 2
        assert tracker.day_pnl == -5000.0

    def test_restore_no_snapshot(self):
        """No snapshot for today → start fresh (all zeros)."""
        client = _mock_supabase(existing_snapshot=None)
        tracker = DrawdownTracker(client)

        state = tracker.restore_state()

        assert state["day_pnl"] == 0.0
        assert state["total_trades"] == 0
        assert state["winning_trades"] == 0
        assert state["losing_trades"] == 0

    def test_restore_handles_exception(self):
        """Database failure → graceful degradation with zeros."""
        client = MagicMock()
        client.table.side_effect = Exception("DB connection failed")
        tracker = DrawdownTracker(client)

        state = tracker.restore_state()

        assert state["day_pnl"] == 0.0
        assert state["total_trades"] == 0

    def test_restore_partial_snapshot(self):
        """Snapshot with missing fields → defaults to zero."""
        snapshot = {
            "id": "snap-002",
            "day_pnl": -1000.0,
            # Missing: total_trades, winning_trades, losing_trades
        }
        client = _mock_supabase(existing_snapshot=snapshot)
        tracker = DrawdownTracker(client)

        state = tracker.restore_state()

        assert state["day_pnl"] == -1000.0
        assert state["total_trades"] == 0  # Defaults to 0


# ── Record P&L tests ─────────────────────────────────────────────────────────


class TestRecordPnl:
    def test_profit_increments_winning_trades(self):
        client = _mock_supabase()
        tracker = DrawdownTracker(client)

        tracker.record_pnl(500.0, portfolio_value=1_000_000)

        assert tracker.day_pnl == 500.0
        assert tracker.total_trades == 1
        assert tracker.winning_trades == 1
        assert tracker.losing_trades == 0

    def test_loss_increments_losing_trades(self):
        client = _mock_supabase()
        tracker = DrawdownTracker(client)

        tracker.record_pnl(-300.0, portfolio_value=1_000_000)

        assert tracker.day_pnl == -300.0
        assert tracker.total_trades == 1
        assert tracker.winning_trades == 0
        assert tracker.losing_trades == 1

    def test_zero_pnl_is_neutral(self):
        """Breakeven trade should count but not as win or loss."""
        client = _mock_supabase()
        tracker = DrawdownTracker(client)

        tracker.record_pnl(0.0)

        assert tracker.total_trades == 1
        assert tracker.winning_trades == 0
        assert tracker.losing_trades == 0

    def test_multiple_trades_accumulate(self):
        client = _mock_supabase()
        tracker = DrawdownTracker(client)

        tracker.record_pnl(1000.0)
        tracker.record_pnl(-500.0)
        tracker.record_pnl(200.0)

        assert tracker.day_pnl == 700.0
        assert tracker.total_trades == 3
        assert tracker.winning_trades == 2
        assert tracker.losing_trades == 1

    def test_record_persists_to_supabase(self):
        """Each record_pnl should trigger an upsert to Supabase."""
        client = _mock_supabase()
        tracker = DrawdownTracker(client)

        tracker.record_pnl(500.0, portfolio_value=1_000_000, cash=500_000)

        # Verify upsert was called with correct data
        table = client.table.return_value
        table.upsert.assert_called_once()
        call_args = table.upsert.call_args[0][0]
        assert call_args["day_pnl"] == "500.0"
        assert call_args["total_trades"] == 1
        assert call_args["winning_trades"] == 1
        assert call_args["losing_trades"] == 0

    def test_persist_failure_does_not_crash(self):
        """If upsert fails, record_pnl should NOT raise."""
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        table.upsert.side_effect = Exception("Network error")
        tracker = DrawdownTracker(client)

        # Should not raise
        tracker.record_pnl(-500.0)

        assert tracker.day_pnl == -500.0
        assert tracker.total_trades == 1


# ── Restore then record ──────────────────────────────────────────────────────


class TestRestoreAndRecord:
    """Integration: restore yesterday's snapshot, then record new trades."""

    def test_continues_from_restored_state(self):
        """Restored state + new trades should accumulate correctly."""
        snapshot = {
            "id": "snap-003",
            "day_pnl": -2000.0,
            "total_trades": 2,
            "winning_trades": 0,
            "losing_trades": 2,
        }
        client = _mock_supabase(existing_snapshot=snapshot)
        tracker = DrawdownTracker(client)

        tracker.restore_state()
        tracker.record_pnl(1500.0)  # Win

        assert tracker.day_pnl == -500.0  # -2000 + 1500
        assert tracker.total_trades == 3
        assert tracker.winning_trades == 1
        assert tracker.losing_trades == 2

    def test_snapshot_id_preserved_for_update(self):
        """After restore, upsert should include the snapshot ID for update."""
        snapshot = {"id": "snap-004", "day_pnl": 0, "total_trades": 0,
                    "winning_trades": 0, "losing_trades": 0}
        client = _mock_supabase(existing_snapshot=snapshot)
        tracker = DrawdownTracker(client)

        tracker.restore_state()
        tracker.record_pnl(100.0)

        table = client.table.return_value
        call_args = table.upsert.call_args[0][0]
        assert call_args.get("id") == "snap-004"

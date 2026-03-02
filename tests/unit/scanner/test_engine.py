"""Tests for the scanner engine."""

import asyncio
import json

import pytest

from skopaq.scanner.engine import ScannerEngine
from skopaq.scanner.models import ScannerCandidate
from skopaq.scanner.watchlist import Watchlist


def _make_quotes(symbols: list[str]) -> list[dict]:
    """Build fake quote dicts for testing."""
    return [
        {
            "symbol": s,
            "ltp": 1000 + i * 100,
            "open": 990 + i * 100,
            "high": 1050 + i * 100,
            "low": 970 + i * 100,
            "close": 995 + i * 100,
            "volume": 50000 * (i + 1),
            "avg_volume": 40000 * (i + 1),
        }
        for i, s in enumerate(symbols)
    ]


def _make_llm_response(symbols: list[str]) -> str:
    """Build a fake LLM JSON response."""
    return json.dumps([
        {"symbol": s, "reason": f"{s} looks good", "urgency": "normal"}
        for s in symbols
    ])


class TestScannerEngine:
    def test_default_watchlist(self):
        engine = ScannerEngine()
        assert len(engine.watchlist) > 0

    def test_custom_watchlist(self):
        wl = Watchlist(["RELIANCE", "TCS"])
        engine = ScannerEngine(watchlist=wl)
        assert len(engine.watchlist) == 2

    def test_compute_metrics(self):
        quotes = _make_quotes(["RELIANCE"])
        metrics = ScannerEngine._compute_metrics(quotes)

        assert len(metrics) == 1
        m = metrics[0]
        assert m.symbol == "RELIANCE"
        assert m.ltp == 1000
        assert m.volume == 50000
        assert m.volume_ratio > 0

    def test_compute_metrics_change_pct(self):
        quotes = [{"symbol": "A", "ltp": 110, "close": 100, "open": 105, "volume": 1000, "avg_volume": 1000}]
        metrics = ScannerEngine._compute_metrics(quotes)
        assert metrics[0].change_pct == 10.0  # (110-100)/100 * 100

    def test_compute_metrics_gap_pct(self):
        quotes = [{"symbol": "A", "ltp": 100, "close": 100, "open": 102, "volume": 1000, "avg_volume": 1000}]
        metrics = ScannerEngine._compute_metrics(quotes)
        assert metrics[0].gap_pct == 2.0  # (102-100)/100 * 100

    def test_compute_metrics_missing_fields(self):
        quotes = [{"symbol": "A"}]
        metrics = ScannerEngine._compute_metrics(quotes)
        assert len(metrics) == 1
        assert metrics[0].symbol == "A"
        assert metrics[0].ltp == 0.0

    @pytest.mark.asyncio
    async def test_scan_once_with_mocks(self):
        """Full scan cycle with mocked fetcher + screener."""
        symbols = ["RELIANCE", "TCS"]

        async def mock_fetcher(syms):
            return _make_quotes(syms)

        async def mock_screener(prompt):
            return _make_llm_response(["RELIANCE"])

        engine = ScannerEngine(
            watchlist=Watchlist(symbols),
            quote_fetcher=mock_fetcher,
            llm_screener=mock_screener,
        )

        candidates = await engine.scan_once()
        assert len(candidates) == 1
        assert candidates[0].symbol == "RELIANCE"

    @pytest.mark.asyncio
    async def test_scan_once_empty_quotes(self):
        """Empty quotes → no candidates."""
        async def mock_fetcher(syms):
            return []

        engine = ScannerEngine(
            watchlist=Watchlist(["A"]),
            quote_fetcher=mock_fetcher,
        )

        candidates = await engine.scan_once()
        assert candidates == []

    @pytest.mark.asyncio
    async def test_scan_once_increments_cycle_count(self):
        async def mock_fetcher(syms):
            return []

        engine = ScannerEngine(
            watchlist=Watchlist(["A"]),
            quote_fetcher=mock_fetcher,
        )

        assert engine._cycle_count == 0
        await engine.scan_once()
        assert engine._cycle_count == 1
        await engine.scan_once()
        assert engine._cycle_count == 2

    @pytest.mark.asyncio
    async def test_status_property(self):
        engine = ScannerEngine(
            watchlist=Watchlist(["A", "B"]),
            cycle_seconds=15,
        )

        status = engine.status
        assert status["running"] is False
        assert status["cycle_count"] == 0
        assert status["watchlist_size"] == 2
        assert status["cycle_seconds"] == 15

    @pytest.mark.asyncio
    async def test_default_fetcher_returns_empty(self):
        """Default quote fetcher (paper stub) returns no data."""
        engine = ScannerEngine(watchlist=Watchlist(["A"]))
        candidates = await engine.scan_once()
        assert candidates == []

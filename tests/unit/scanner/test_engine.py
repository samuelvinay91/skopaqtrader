"""Tests for the scanner engine."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

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


class TestInitTavilyClient:
    def test_returns_none_when_no_env_var(self):
        env = {"SKOPAQ_TRADING_MODE": "paper"}
        with patch.dict("os.environ", env, clear=True):
            client = ScannerEngine._init_tavily_client()
            assert client is None

    def test_returns_client_when_tavily_key_set(self):
        import unittest.mock as um
        mock_module = um.MagicMock()
        mock_client_instance = um.MagicMock()
        mock_module.AsyncTavilyClient.return_value = mock_client_instance

        with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test123"}, clear=False):
            with patch.dict("sys.modules", {"tavily": mock_module}):
                client = ScannerEngine._init_tavily_client()
                assert client is mock_client_instance
                mock_module.AsyncTavilyClient.assert_called_once_with(api_key="tvly-test123")

    def test_returns_client_when_skopaq_key_set(self):
        import unittest.mock as um
        mock_module = um.MagicMock()
        mock_client_instance = um.MagicMock()
        mock_module.AsyncTavilyClient.return_value = mock_client_instance

        env = {"SKOPAQ_TAVILY_API_KEY": "tvly-test456", "SKOPAQ_TRADING_MODE": "paper"}
        with patch.dict("os.environ", env, clear=True):
            with patch.dict("sys.modules", {"tavily": mock_module}):
                client = ScannerEngine._init_tavily_client()
                assert client is mock_client_instance

    def test_returns_none_on_import_error(self):
        import sys as _sys
        # Remove tavily from sys.modules if present, then make import fail
        with patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test123"}, clear=False):
            with patch.dict("sys.modules", {"tavily": None}):
                client = ScannerEngine._init_tavily_client()
                assert client is None


class TestScreenNewsTavily:
    @pytest.mark.asyncio
    async def test_calls_tavily_and_returns_candidates(self):
        mock_client = AsyncMock()
        mock_client.search.return_value = {
            "results": [
                {"title": "RELIANCE surges on strong Q4", "content": "Details.", "score": 0.9, "url": "http://example.com"},
            ]
        }

        engine = ScannerEngine(watchlist=Watchlist(["RELIANCE"]))
        engine._tavily_client = mock_client

        candidates = await engine._screen_news_tavily(["RELIANCE"])
        assert len(candidates) >= 1
        assert candidates[0].metrics["source"] == "news_tavily"
        mock_client.search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty(self):
        mock_client = AsyncMock()
        mock_client.search.return_value = {"results": []}

        engine = ScannerEngine(watchlist=Watchlist(["A"]))
        engine._tavily_client = mock_client

        candidates = await engine._screen_news_tavily(["A"])
        assert candidates == []

    @pytest.mark.asyncio
    async def test_tavily_included_in_parallel_screeners(self):
        """When _tavily_client is set, it runs alongside other screeners."""
        mock_client = AsyncMock()
        mock_client.search.return_value = {"results": []}

        async def mock_fetcher(syms):
            return _make_quotes(syms)

        async def mock_screener(prompt):
            return "[]"

        engine = ScannerEngine(
            watchlist=Watchlist(["A"]),
            quote_fetcher=mock_fetcher,
            llm_screener=mock_screener,
        )
        engine._tavily_client = mock_client

        await engine.scan_once()
        mock_client.search.assert_awaited_once()

"""Tests for PaperEngine async methods (MarketDataProvider integration).

Covers: execute_order_async, refresh_quote, get_positions_live, set_market_data.
These methods enable live-data paper trading with auto-refreshed quotes.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from skopaq.broker.models import (
    Exchange,
    OrderRequest,
    OrderType,
    Product,
    Quote,
    Side,
)
from skopaq.broker.paper_engine import PaperEngine


def _market_buy(symbol="RELIANCE", qty=10):
    return OrderRequest(
        symbol=symbol, exchange=Exchange.NSE, side=Side.BUY,
        quantity=qty, order_type=OrderType.MARKET, product=Product.CNC,
    )


def _quote(symbol="RELIANCE", ltp=2500.0):
    return Quote(symbol=symbol, exchange="NSE", ltp=ltp, bid=ltp - 1, ask=ltp + 1)


def _mock_provider(**overrides):
    """Create a mock MarketDataProvider with correct sync/async signatures."""
    provider = AsyncMock()
    # inject_quote is synchronous — override to avoid coroutine warnings
    provider.inject_quote = MagicMock()
    for k, v in overrides.items():
        setattr(provider, k, v)
    return provider


# ── set_market_data ──────────────────────────────────────────────────────────


class TestSetMarketData:
    def test_attaches_provider(self):
        engine = PaperEngine()
        provider = MagicMock()
        engine.set_market_data(provider)
        assert engine._market_data is provider

    def test_constructor_accepts_market_data(self):
        provider = MagicMock()
        engine = PaperEngine(market_data=provider)
        assert engine._market_data is provider

    def test_default_is_none(self):
        engine = PaperEngine()
        assert engine._market_data is None


# ── update_quote with provider ───────────────────────────────────────────────


class TestUpdateQuoteWithProvider:
    def test_update_quote_pushes_to_provider_cache(self):
        provider = _mock_provider()
        engine = PaperEngine(market_data=provider)
        quote = _quote("RELIANCE", 2500)
        engine.update_quote(quote)

        provider.inject_quote.assert_called_once_with(quote)
        assert engine.get_quote("RELIANCE") is quote

    def test_update_quote_without_provider_still_works(self):
        engine = PaperEngine()
        quote = _quote("RELIANCE", 2500)
        engine.update_quote(quote)
        assert engine.get_quote("RELIANCE") is quote


# ── refresh_quote ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRefreshQuote:
    async def test_fetches_from_provider(self):
        provider = _mock_provider()
        fresh = _quote("RELIANCE", 2550)
        provider.get_quote = AsyncMock(return_value=fresh)

        engine = PaperEngine(market_data=provider)
        result = await engine.refresh_quote("RELIANCE")

        provider.get_quote.assert_called_once_with("RELIANCE")
        assert result.ltp == 2550
        assert engine.get_quote("RELIANCE").ltp == 2550

    async def test_falls_back_to_cache_without_provider(self):
        engine = PaperEngine()
        engine.update_quote(_quote("RELIANCE", 2500))
        result = await engine.refresh_quote("RELIANCE")
        assert result.ltp == 2500

    async def test_returns_none_when_no_cache_no_provider(self):
        engine = PaperEngine()
        result = await engine.refresh_quote("NONEXISTENT")
        assert result is None

    async def test_ignores_zero_ltp_from_provider(self):
        provider = _mock_provider()
        provider.get_quote = AsyncMock(return_value=_quote("RELIANCE", 0.0))

        engine = PaperEngine(market_data=provider)
        engine.update_quote(_quote("RELIANCE", 2500))
        result = await engine.refresh_quote("RELIANCE")

        # Should keep old cached value since provider returned 0
        assert result.ltp == 2500


# ── execute_order_async ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestExecuteOrderAsync:
    async def test_refreshes_quote_before_fill(self):
        """execute_order_async should fetch fresh quote then fill."""
        provider = _mock_provider()
        fresh = _quote("RELIANCE", 2550)
        provider.get_quote = AsyncMock(return_value=fresh)

        engine = PaperEngine(
            initial_capital=1_000_000, slippage_pct=0.0, brokerage=0.0,
            market_data=provider,
        )
        # Inject stale quote
        engine.update_quote(_quote("RELIANCE", 2500))

        order = _market_buy("RELIANCE", qty=10)
        result = await engine.execute_order_async(order)

        assert result.success
        # Fill should be at the REFRESHED ask price (2551), not stale (2501)
        assert result.fill_price == 2551.0
        provider.get_quote.assert_called_with("RELIANCE")

    async def test_works_without_provider(self):
        """Without provider, behaves like sync execute_order."""
        engine = PaperEngine(
            initial_capital=1_000_000, slippage_pct=0.0, brokerage=0.0,
        )
        engine.update_quote(_quote("RELIANCE", 2500))

        order = _market_buy("RELIANCE", qty=10)
        result = await engine.execute_order_async(order)

        assert result.success
        assert result.fill_price == 2501.0  # ask from stale quote

    async def test_provider_failure_uses_cached(self):
        """If provider returns 0 LTP, fall back to cached quote."""
        provider = _mock_provider()
        provider.get_quote = AsyncMock(return_value=_quote("RELIANCE", 0.0))

        engine = PaperEngine(
            initial_capital=1_000_000, slippage_pct=0.0, brokerage=0.0,
            market_data=provider,
        )
        engine.update_quote(_quote("RELIANCE", 2500))

        order = _market_buy("RELIANCE", qty=10)
        result = await engine.execute_order_async(order)

        assert result.success
        assert result.fill_price == 2501.0  # Used cached quote

    async def test_no_quote_anywhere_rejects(self):
        """No cached quote and provider returns 0 → rejected."""
        provider = _mock_provider()
        provider.get_quote = AsyncMock(return_value=_quote("UNKNOWN", 0.0))

        engine = PaperEngine(
            initial_capital=1_000_000, market_data=provider,
        )
        order = _market_buy("UNKNOWN", qty=10)
        result = await engine.execute_order_async(order)

        assert not result.success
        assert "No quote" in result.rejection_reason


# ── get_positions_live ───────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetPositionsLive:
    async def test_refreshes_quotes_for_open_positions(self):
        provider = _mock_provider()
        provider.get_quotes = AsyncMock(return_value=[
            _quote("RELIANCE", 2600),
        ])

        engine = PaperEngine(
            initial_capital=1_000_000, slippage_pct=0.0, brokerage=0.0,
            market_data=provider,
        )
        engine.update_quote(_quote("RELIANCE", 2500))
        engine.execute_order(_market_buy("RELIANCE", qty=10))

        positions = await engine.get_positions_live()

        provider.get_quotes.assert_called_once_with(["RELIANCE"])
        assert len(positions) == 1
        assert positions[0].last_price == 2600.0
        # P&L should reflect refreshed price: (2600 - 2501) * 10 = 990
        assert positions[0].pnl == pytest.approx(990.0, abs=1)

    async def test_no_positions_no_fetch(self):
        provider = _mock_provider()
        provider.get_quotes = AsyncMock()

        engine = PaperEngine(market_data=provider)
        positions = await engine.get_positions_live()

        assert positions == []
        provider.get_quotes.assert_not_called()

    async def test_without_provider_returns_cached(self):
        engine = PaperEngine(
            initial_capital=1_000_000, slippage_pct=0.0, brokerage=0.0,
        )
        engine.update_quote(_quote("RELIANCE", 2500))
        engine.execute_order(_market_buy("RELIANCE", qty=10))

        positions = await engine.get_positions_live()
        assert len(positions) == 1
        assert positions[0].last_price == 2500.0

"""Integration tests — Binance public API connectivity.

Tests real API calls to Binance public endpoints (no authentication needed).
These are unauthenticated/read-only endpoints, safe to call freely.
Rate limit: 1200 weight/minute.
"""

import pytest

from skopaq.broker.binance_client import BinanceClient, BinanceError
from skopaq.broker.models import Exchange, Quote

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class TestBinanceLiveQuote:
    """Fetch real quotes from Binance public API."""

    async def test_btcusdt_quote(self):
        """BTCUSDT returns a valid quote with positive price."""
        async with BinanceClient() as client:
            quote = await client.get_quote("BTCUSDT")

        assert isinstance(quote, Quote)
        assert quote.symbol == "BTCUSDT"
        assert quote.exchange == Exchange.BINANCE
        assert quote.ltp > 0
        assert quote.volume > 0

    async def test_ethusdt_quote(self):
        """ETHUSDT returns a valid quote with all fields populated."""
        async with BinanceClient() as client:
            quote = await client.get_quote("ETHUSDT")

        assert quote.symbol == "ETHUSDT"
        assert quote.ltp > 0
        assert quote.high >= quote.low
        assert quote.bid > 0
        assert quote.ask > 0

    async def test_all_quote_fields_populated(self):
        """Verify every Quote field is populated for a major pair."""
        async with BinanceClient() as client:
            quote = await client.get_quote("BTCUSDT")

        # Price fields
        assert quote.ltp > 0, "ltp (last traded price) should be positive"
        assert quote.open > 0, "open price should be positive"
        assert quote.high > 0, "high price should be positive"
        assert quote.low > 0, "low price should be positive"
        assert quote.close > 0, "close (prev close) should be positive"

        # Depth fields
        assert quote.bid > 0, "bid should be positive"
        assert quote.ask > 0, "ask should be positive"
        assert quote.ask >= quote.bid, "ask should be >= bid"

        # Volume
        assert quote.volume > 0, "volume should be positive"

        # Change (can be negative, just check it's not None/zero default)
        assert quote.change_pct != 0 or quote.change != 0, "change should be non-zero"

    async def test_invalid_symbol_raises(self):
        """Invalid symbol returns a 400 error."""
        async with BinanceClient() as client:
            with pytest.raises(BinanceError) as exc_info:
                await client.get_quote("NOTAREALPAIRZZZUSDT")

        assert exc_info.value.status_code == 400


class TestBinanceLivePrice:
    """Fetch real prices from Binance ticker/price endpoint."""

    async def test_btcusdt_price(self):
        """Quick price check returns a positive float."""
        async with BinanceClient() as client:
            price = await client.get_price("BTCUSDT")

        assert isinstance(price, float)
        assert price > 1000  # BTC is well above 1000 USDT

    async def test_solusdt_price(self):
        """SOL price is in reasonable range."""
        async with BinanceClient() as client:
            price = await client.get_price("SOLUSDT")

        assert price > 0


class TestBinanceLiveExchangeInfo:
    """Fetch real exchange info for symbol metadata."""

    async def test_btcusdt_exchange_info(self):
        """Exchange info contains filters and asset details."""
        async with BinanceClient() as client:
            info = await client.get_exchange_info("BTCUSDT")

        assert info["symbol"] == "BTCUSDT"
        assert info["baseAsset"] == "BTC"
        assert info["quoteAsset"] == "USDT"
        assert len(info["filters"]) > 0

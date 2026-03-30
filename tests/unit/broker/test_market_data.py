"""Tests for MarketDataProvider."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skopaq.broker.market_data import (
    MarketDataProvider,
    _to_yfinance_symbol,
)
from skopaq.broker.models import Quote


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.broker = "indstocks"
    config.asset_class = "equity"
    config.binance_base_url = "https://api.binance.com"
    return config


@pytest.fixture
def provider(mock_config):
    return MarketDataProvider(mock_config, stale_threshold=5.0)


class TestYfinanceSymbolConversion:
    def test_plain_indian_equity(self):
        assert _to_yfinance_symbol("RELIANCE") == "RELIANCE.NS"

    def test_already_ns(self):
        assert _to_yfinance_symbol("RELIANCE.NS") == "RELIANCE.NS"

    def test_already_bo(self):
        assert _to_yfinance_symbol("RELIANCE.BO") == "RELIANCE.BO"

    def test_crypto_usdt(self):
        assert _to_yfinance_symbol("BTCUSDT") == "BTC-USD"

    def test_crypto_already_usd(self):
        assert _to_yfinance_symbol("BTC-USD") == "BTC-USD"

    def test_kite_nse_prefix(self):
        assert _to_yfinance_symbol("NSE:RELIANCE") == "RELIANCE.NS"

    def test_kite_bse_prefix(self):
        assert _to_yfinance_symbol("BSE:RELIANCE") == "RELIANCE.BO"

    def test_crypto_busd(self):
        assert _to_yfinance_symbol("ETHBUSD") == "ETH-USD"

    def test_short_symbol(self):
        # "ETH" alone shouldn't trigger crypto detection
        assert _to_yfinance_symbol("ETH") == "ETH.NS"


class TestMarketDataProviderCache:
    def test_put_and_get_fresh(self, provider):
        quote = Quote(symbol="RELIANCE", ltp=2500.0)
        provider._put_cache("RELIANCE", quote)
        cached = provider._get_cached("RELIANCE")
        assert cached is not None
        assert cached.ltp == 2500.0

    def test_stale_cache_returns_none(self, provider):
        quote = Quote(symbol="RELIANCE", ltp=2500.0)
        provider._put_cache("RELIANCE", quote)
        # Fake the timestamp to be old
        provider._cache["RELIANCE"] = (quote, time.monotonic() - 100)
        assert provider._get_cached("RELIANCE") is None

    def test_stale_cache_with_ignore(self, provider):
        quote = Quote(symbol="RELIANCE", ltp=2500.0)
        provider._put_cache("RELIANCE", quote)
        provider._cache["RELIANCE"] = (quote, time.monotonic() - 100)
        cached = provider._get_cached("RELIANCE", ignore_staleness=True)
        assert cached is not None
        assert cached.ltp == 2500.0

    def test_missing_cache_returns_none(self, provider):
        assert provider._get_cached("NONEXISTENT") is None

    def test_clear_cache(self, provider):
        provider._put_cache("A", Quote(symbol="A", ltp=100))
        provider._put_cache("B", Quote(symbol="B", ltp=200))
        provider.clear_cache()
        assert provider._get_cached("A") is None
        assert provider._get_cached("B") is None


class TestMarketDataProviderInject:
    def test_inject_quote(self, provider):
        quote = Quote(symbol="TCS", ltp=3500.0)
        provider.inject_quote(quote)
        cached = provider._get_cached("TCS")
        assert cached is not None
        assert cached.ltp == 3500.0


@pytest.mark.asyncio
class TestMarketDataProviderBrokerSource:
    async def test_broker_quote_indstocks(self, provider):
        mock_client = AsyncMock()
        mock_client.get_quote = AsyncMock(
            return_value=Quote(symbol="RELIANCE", ltp=2500.0, bid=2499.0, ask=2501.0)
        )
        provider.set_broker_client(mock_client)

        with patch("skopaq.broker.scrip_resolver.resolve_scrip_code", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = "NSE_2885"
            quote = await provider._fetch_broker_quote("RELIANCE")

        assert quote is not None
        assert quote.ltp == 2500.0
        assert quote.bid == 2499.0

    async def test_broker_quote_kite(self, mock_config):
        mock_config.broker = "kite"
        p = MarketDataProvider(mock_config)

        mock_client = AsyncMock()
        mock_client.get_quote = AsyncMock(
            return_value=Quote(symbol="RELIANCE", ltp=2500.0)
        )
        p.set_broker_client(mock_client)

        quote = await p._fetch_broker_quote("RELIANCE")
        assert quote is not None
        assert quote.ltp == 2500.0
        mock_client.get_quote.assert_called_once_with("NSE:RELIANCE", symbol="RELIANCE")

    async def test_no_broker_returns_none(self, provider):
        quote = await provider._fetch_broker_quote("RELIANCE")
        assert quote is None

    async def test_broker_error_returns_none(self, provider):
        mock_client = AsyncMock()
        mock_client.get_quote = AsyncMock(side_effect=Exception("Token expired"))
        provider.set_broker_client(mock_client)

        with patch("skopaq.broker.scrip_resolver.resolve_scrip_code", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = "NSE_2885"
            quote = await provider._fetch_broker_quote("RELIANCE")

        assert quote is None


@pytest.mark.asyncio
class TestMarketDataProviderYfinance:
    async def test_yfinance_fallback(self, provider):
        """Test that yfinance is called when no broker is attached."""
        fake_quote = Quote(symbol="RELIANCE", ltp=2500.0, exchange="NSE")

        with patch.object(provider, "_fetch_yfinance_quote", new_callable=AsyncMock) as mock_yf:
            mock_yf.return_value = fake_quote
            quote = await provider.get_quote("RELIANCE")

        assert quote.ltp == 2500.0
        mock_yf.assert_called_once()

    async def test_yfinance_sync_import_error(self):
        """Test graceful handling when yfinance is not installed."""
        with patch.dict("sys.modules", {"yfinance": None}):
            result = MarketDataProvider._yfinance_sync("RELIANCE")
            # Should return None, not raise
            assert result is None


@pytest.mark.asyncio
class TestMarketDataProviderGetQuote:
    async def test_returns_cached_if_fresh(self, provider):
        provider._put_cache("RELIANCE", Quote(symbol="RELIANCE", ltp=2500.0))
        quote = await provider.get_quote("RELIANCE")
        assert quote.ltp == 2500.0

    async def test_tries_broker_then_yfinance(self, provider):
        """When broker fails, falls back to yfinance."""
        # Mock broker to fail
        with patch.object(
            provider, "_fetch_broker_quote", new_callable=AsyncMock, return_value=None,
        ):
            with patch.object(
                provider, "_fetch_yfinance_quote", new_callable=AsyncMock,
            ) as mock_yf:
                mock_yf.return_value = Quote(symbol="RELIANCE", ltp=2500.0)
                quote = await provider.get_quote("RELIANCE")

        assert quote.ltp == 2500.0
        mock_yf.assert_called_once()

    async def test_returns_stale_on_total_failure(self, provider):
        """When all sources fail, returns stale cache."""
        provider._put_cache("RELIANCE", Quote(symbol="RELIANCE", ltp=2500.0))
        # Make it stale
        provider._cache["RELIANCE"] = (
            provider._cache["RELIANCE"][0],
            time.monotonic() - 100,
        )

        with patch.object(
            provider, "_fetch_broker_quote", new_callable=AsyncMock, return_value=None,
        ):
            with patch.object(
                provider, "_fetch_yfinance_quote", new_callable=AsyncMock, return_value=None,
            ):
                quote = await provider.get_quote("RELIANCE")

        assert quote.ltp == 2500.0  # Stale but better than nothing

    async def test_returns_empty_quote_on_total_miss(self, provider):
        """When no cache and all sources fail, returns zero Quote."""
        with patch.object(
            provider, "_fetch_broker_quote", new_callable=AsyncMock, return_value=None,
        ):
            with patch.object(
                provider, "_fetch_yfinance_quote", new_callable=AsyncMock, return_value=None,
            ):
                quote = await provider.get_quote("NONEXISTENT")

        assert quote.symbol == "NONEXISTENT"
        assert quote.ltp == 0.0


@pytest.mark.asyncio
class TestMarketDataProviderGetLtp:
    async def test_get_ltp(self, provider):
        provider._put_cache("RELIANCE", Quote(symbol="RELIANCE", ltp=2500.0))
        ltp = await provider.get_ltp("RELIANCE")
        assert ltp == 2500.0

    async def test_get_ltp_zero_on_miss(self, provider):
        with patch.object(
            provider, "_fetch_broker_quote", new_callable=AsyncMock, return_value=None,
        ):
            with patch.object(
                provider, "_fetch_yfinance_quote", new_callable=AsyncMock, return_value=None,
            ):
                ltp = await provider.get_ltp("NONEXISTENT")
        assert ltp == 0.0


@pytest.mark.asyncio
class TestMarketDataProviderGetQuotes:
    async def test_get_quotes_concurrent(self, provider):
        provider._put_cache("A", Quote(symbol="A", ltp=100))
        provider._put_cache("B", Quote(symbol="B", ltp=200))
        quotes = await provider.get_quotes(["A", "B"])
        assert len(quotes) == 2
        assert quotes[0].ltp == 100
        assert quotes[1].ltp == 200


@pytest.mark.asyncio
class TestMarketDataProviderCrypto:
    async def test_binance_fallback_for_crypto(self):
        config = MagicMock()
        config.broker = "indstocks"
        config.asset_class = "crypto"
        config.binance_base_url = "https://api.binance.com"
        provider = MarketDataProvider(config)

        with patch.object(
            provider, "_fetch_broker_quote", new_callable=AsyncMock, return_value=None,
        ):
            with patch.object(
                provider, "_fetch_yfinance_quote", new_callable=AsyncMock, return_value=None,
            ):
                with patch.object(
                    provider, "_fetch_binance_quote", new_callable=AsyncMock,
                    return_value=Quote(symbol="BTCUSDT", ltp=65000.0),
                ) as mock_binance:
                    quote = await provider.get_quote("BTCUSDT")

        assert quote.ltp == 65000.0
        mock_binance.assert_called_once()

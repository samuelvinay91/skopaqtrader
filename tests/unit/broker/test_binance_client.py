"""Tests for the Binance public API client (mocked HTTP)."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from skopaq.broker.binance_client import BinanceClient, BinanceError
from skopaq.broker.models import Exchange, Quote


# ── Fixtures ──────────────────────────────────────────────────────────────────

MOCK_24HR_RESPONSE = {
    "symbol": "BTCUSDT",
    "lastPrice": "67890.50",
    "openPrice": "66000.00",
    "highPrice": "68500.00",
    "lowPrice": "65500.00",
    "prevClosePrice": "66100.00",
    "volume": "12345.678",
    "bidPrice": "67889.00",
    "askPrice": "67891.00",
    "priceChange": "1790.50",
    "priceChangePercent": "2.71",
}

MOCK_PRICE_RESPONSE = {
    "symbol": "BTCUSDT",
    "price": "67890.50",
}

MOCK_EXCHANGE_INFO_RESPONSE = {
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "baseAsset": "BTC",
            "quoteAsset": "USDT",
            "filters": [
                {"filterType": "LOT_SIZE", "minQty": "0.00001", "stepSize": "0.00001"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "10.00"},
            ],
        }
    ]
}


def _mock_response(json_data, status_code=200, headers=None):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.headers = headers or {}
    resp.text = str(json_data)[:500]
    return resp


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestBinanceClientQuote:
    @pytest.mark.asyncio
    async def test_get_quote_success(self):
        """24hr ticker endpoint returns a valid Quote model."""
        async with BinanceClient() as client:
            client._client = AsyncMock(spec=httpx.AsyncClient)
            client._client.get = AsyncMock(
                return_value=_mock_response(MOCK_24HR_RESPONSE)
            )

            quote = await client.get_quote("BTCUSDT")

            assert isinstance(quote, Quote)
            assert quote.symbol == "BTCUSDT"
            assert quote.exchange == Exchange.BINANCE
            assert quote.ltp == 67890.50
            assert quote.open == 66000.0
            assert quote.high == 68500.0
            assert quote.low == 65500.0
            assert quote.close == 66100.0
            assert quote.volume == 12345
            assert quote.bid == 67889.0
            assert quote.ask == 67891.0
            assert quote.change == 1790.50
            assert quote.change_pct == 2.71

    @pytest.mark.asyncio
    async def test_get_quote_uppercases_symbol(self):
        """Symbol is normalised to uppercase before API call."""
        async with BinanceClient() as client:
            client._client = AsyncMock(spec=httpx.AsyncClient)
            client._client.get = AsyncMock(
                return_value=_mock_response(MOCK_24HR_RESPONSE)
            )

            await client.get_quote("btcusdt")

            call_args = client._client.get.call_args
            assert call_args[1]["params"]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_get_quote_api_error(self):
        """Non-200 response raises BinanceError."""
        async with BinanceClient() as client:
            client._client = AsyncMock(spec=httpx.AsyncClient)
            client._client.get = AsyncMock(
                return_value=_mock_response(
                    {"code": -1121, "msg": "Invalid symbol."},
                    status_code=400,
                )
            )

            with pytest.raises(BinanceError) as exc_info:
                await client.get_quote("FAKECOIN")

            assert exc_info.value.status_code == 400


class TestBinanceClientPrice:
    @pytest.mark.asyncio
    async def test_get_price_success(self):
        """Price endpoint returns a float."""
        async with BinanceClient() as client:
            client._client = AsyncMock(spec=httpx.AsyncClient)
            client._client.get = AsyncMock(
                return_value=_mock_response(MOCK_PRICE_RESPONSE)
            )

            price = await client.get_price("BTCUSDT")

            assert price == 67890.50
            assert isinstance(price, float)


class TestBinanceClientExchangeInfo:
    @pytest.mark.asyncio
    async def test_get_exchange_info_success(self):
        """Exchange info returns symbol metadata dict."""
        async with BinanceClient() as client:
            client._client = AsyncMock(spec=httpx.AsyncClient)
            client._client.get = AsyncMock(
                return_value=_mock_response(MOCK_EXCHANGE_INFO_RESPONSE)
            )

            info = await client.get_exchange_info("BTCUSDT")

            assert info["symbol"] == "BTCUSDT"
            assert info["baseAsset"] == "BTC"
            assert len(info["filters"]) == 2

    @pytest.mark.asyncio
    async def test_get_exchange_info_empty_symbols(self):
        """Empty symbols list raises BinanceError."""
        async with BinanceClient() as client:
            client._client = AsyncMock(spec=httpx.AsyncClient)
            client._client.get = AsyncMock(
                return_value=_mock_response({"symbols": []})
            )

            with pytest.raises(BinanceError):
                await client.get_exchange_info("FAKEPAIR")


class TestBinanceClientRateLimits:
    @pytest.mark.asyncio
    async def test_rate_limit_header_logged(self, caplog):
        """High rate-limit weight triggers a warning."""
        import logging

        async with BinanceClient() as client:
            client._client = AsyncMock(spec=httpx.AsyncClient)
            client._client.get = AsyncMock(
                return_value=_mock_response(
                    MOCK_PRICE_RESPONSE,
                    headers={"X-MBX-USED-WEIGHT-1M": "1100"},
                )
            )

            with caplog.at_level(logging.WARNING, logger="skopaq.broker.binance_client"):
                await client.get_price("BTCUSDT")

            assert any("rate limit" in r.message.lower() for r in caplog.records)


class TestBinanceClientContextManager:
    @pytest.mark.asyncio
    async def test_not_usable_without_context_manager(self):
        """Calling get_quote without async with raises RuntimeError."""
        client = BinanceClient()
        with pytest.raises(RuntimeError, match="async context manager"):
            await client.get_quote("BTCUSDT")

    @pytest.mark.asyncio
    async def test_field_mapping_zero_defaults(self):
        """Missing fields in response default to zero."""
        sparse_data = {"lastPrice": "100.0"}

        async with BinanceClient() as client:
            client._client = AsyncMock(spec=httpx.AsyncClient)
            client._client.get = AsyncMock(
                return_value=_mock_response(sparse_data)
            )

            quote = await client.get_quote("TESTUSDT")

            assert quote.ltp == 100.0
            assert quote.open == 0.0
            assert quote.high == 0.0
            assert quote.bid == 0.0

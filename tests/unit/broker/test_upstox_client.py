"""Tests for Upstox API v2 client."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from skopaq.broker.upstox_client import UpstoxClient, UpstoxError, _EXCHANGE_SEGMENT_MAP


@pytest.fixture
def client():
    return UpstoxClient(access_token="test_access_token")


class TestUpstoxInit:
    def test_creates_with_token(self, client):
        assert client._access_token == "test_access_token"
        assert client._client is None

    def test_headers(self, client):
        headers = client._headers()
        assert headers["Authorization"] == "Bearer test_access_token"


class TestInstrumentKey:
    def test_nse_equity(self):
        assert UpstoxClient._build_instrument_key("RELIANCE", "NSE") == "NSE_EQ|RELIANCE"

    def test_bse_equity(self):
        assert UpstoxClient._build_instrument_key("TCS", "BSE") == "BSE_EQ|TCS"

    def test_nfo(self):
        assert UpstoxClient._build_instrument_key("NIFTY", "NFO") == "NSE_FO|NIFTY"

    def test_default_nse(self):
        assert UpstoxClient._build_instrument_key("INFY") == "NSE_EQ|INFY"

    def test_uppercase(self):
        assert UpstoxClient._build_instrument_key("reliance") == "NSE_EQ|RELIANCE"


class TestLoginUrl:
    def test_format(self):
        url = UpstoxClient.get_login_url("my_key", "http://localhost/callback")
        assert "client_id=my_key" in url
        assert "redirect_uri=http://localhost/callback" in url
        assert "response_type=code" in url


@pytest.mark.asyncio
class TestUpstoxContextManager:
    async def test_aenter_creates_client(self, client):
        async with client as c:
            assert c._client is not None
        assert client._client is None


@pytest.mark.asyncio
class TestUpstoxQuote:
    async def test_get_quote(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "success",
                "data": {
                    "NSE_EQ:RELIANCE": {
                        "last_price": 2500.0,
                        "ohlc": {
                            "open": 2490.0,
                            "high": 2510.0,
                            "low": 2480.0,
                            "close": 2470.0,
                        },
                        "volume": 500000,
                        "depth": {
                            "buy": [{"price": 2499.0, "quantity": 100}],
                            "sell": [{"price": 2501.0, "quantity": 50}],
                        },
                    }
                },
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            quote = await client.get_quote("RELIANCE")

            assert quote.symbol == "RELIANCE"
            assert quote.ltp == 2500.0
            assert quote.open == 2490.0
            assert quote.high == 2510.0
            assert quote.low == 2480.0
            assert quote.close == 2470.0
            assert quote.volume == 500000
            assert quote.bid == 2499.0
            assert quote.ask == 2501.0
            assert quote.change == 30.0
            assert quote.change_pct == pytest.approx(1.21, abs=0.01)

    async def test_get_ltp(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "success",
                "data": {
                    "NSE_EQ:RELIANCE": {"last_price": 2500.0}
                },
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            ltp = await client.get_ltp("RELIANCE")
            assert ltp == 2500.0

    async def test_empty_data_returns_zero(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"status": "success", "data": {}}
            client._client.request = AsyncMock(return_value=mock_resp)

            ltp = await client.get_ltp("NONEXISTENT")
            assert ltp == 0.0


@pytest.mark.asyncio
class TestUpstoxHistorical:
    async def test_get_historical(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "success",
                "data": {
                    "candles": [
                        ["2024-01-15T00:00:00+05:30", 2490, 2510, 2480, 2500, 500000, 0],
                        ["2024-01-16T00:00:00+05:30", 2500, 2520, 2490, 2510, 600000, 0],
                    ]
                },
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            candles = await client.get_historical("RELIANCE")
            assert len(candles) == 2
            assert candles[0].open == 2490
            assert candles[0].close == 2500
            assert candles[0].volume == 500000


@pytest.mark.asyncio
class TestUpstoxErrors:
    async def test_api_error_response(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "error",
                "errors": [{"message": "Invalid token", "errorCode": "UDAPI100050"}],
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(UpstoxError, match="Invalid token"):
                await client._request("GET", "/test")

    async def test_http_error(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_resp.text = "Unauthorized"
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(UpstoxError, match="API error 401"):
                await client._request("GET", "/test")

    async def test_not_initialized(self):
        client = UpstoxClient(access_token="test")
        with pytest.raises(UpstoxError, match="not initialised"):
            await client._request("GET", "/test")


class TestExchangeSegmentMap:
    def test_all_segments_defined(self):
        assert "NSE" in _EXCHANGE_SEGMENT_MAP
        assert "BSE" in _EXCHANGE_SEGMENT_MAP
        assert "NFO" in _EXCHANGE_SEGMENT_MAP
        assert "MCX" in _EXCHANGE_SEGMENT_MAP

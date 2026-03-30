"""Tests for KiteConnectClient."""

import json
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from skopaq.broker.kite_client import (
    KITE_PRODUCT_CNC,
    KITE_PRODUCT_MIS,
    KITE_VARIETY_AMO,
    KITE_VARIETY_REGULAR,
    KiteBrokerError,
    KiteConnectClient,
    _PRODUCT_MAP,
)
from skopaq.broker.models import (
    Exchange,
    Funds,
    Holding,
    OrderRequest,
    OrderResponse,
    OrderType,
    Position,
    Product,
    Quote,
    Side,
    UserProfile,
)


@pytest.fixture
def mock_config():
    """Minimal config mock for KiteConnectClient."""
    config = MagicMock()
    config.kite_api_key = MagicMock()
    config.kite_api_key.get_secret_value.return_value = "test_api_key"
    config.broker = "kite"
    return config


@pytest.fixture
def mock_token_mgr():
    mgr = MagicMock()
    mgr.get_token.return_value = "test_access_token"
    return mgr


@pytest.fixture
def client(mock_config, mock_token_mgr):
    return KiteConnectClient(mock_config, mock_token_mgr)


class TestKiteConnectClientInit:
    def test_creates_with_config(self, mock_config, mock_token_mgr):
        c = KiteConnectClient(mock_config, mock_token_mgr)
        assert c._api_key == "test_api_key"
        assert c._client is None

    def test_headers(self, client):
        headers = client._headers()
        assert headers["Authorization"] == "token test_api_key:test_access_token"
        assert headers["X-Kite-Version"] == "3"


class TestNormalizeInstrumentKey:
    def test_plain_symbol(self):
        assert KiteConnectClient._normalize_instrument_key("RELIANCE") == "NSE:RELIANCE"

    def test_already_prefixed(self):
        assert KiteConnectClient._normalize_instrument_key("NSE:RELIANCE") == "NSE:RELIANCE"

    def test_bse_symbol(self):
        assert KiteConnectClient._normalize_instrument_key("BSE:RELIANCE") == "BSE:RELIANCE"


class TestMapInterval:
    def test_1day(self):
        assert KiteConnectClient._map_interval("1day") == "day"

    def test_1minute(self):
        assert KiteConnectClient._map_interval("1minute") == "minute"

    def test_5minute_passthrough(self):
        assert KiteConnectClient._map_interval("5minute") == "5minute"

    def test_unknown_passthrough(self):
        assert KiteConnectClient._map_interval("3minute") == "3minute"


class TestParseQuote:
    def test_parses_kite_quote(self):
        data = {
            "last_price": 2500.50,
            "ohlc": {"open": 2490.0, "high": 2510.0, "low": 2480.0, "close": 2470.0},
            "volume": 1000000,
            "net_change": 30.5,
            "change": 1.23,
            "depth": {
                "buy": [{"price": 2500.0, "quantity": 100}],
                "sell": [{"price": 2501.0, "quantity": 50}],
            },
        }
        quote = KiteConnectClient._parse_quote(data, "RELIANCE", "NSE:RELIANCE")
        assert quote.symbol == "RELIANCE"
        assert quote.exchange == "NSE"
        assert quote.ltp == 2500.50
        assert quote.open == 2490.0
        assert quote.high == 2510.0
        assert quote.low == 2480.0
        assert quote.close == 2470.0
        assert quote.volume == 1000000
        assert quote.change == 30.5
        assert quote.change_pct == 1.23
        assert quote.bid == 2500.0
        assert quote.ask == 2501.0

    def test_empty_data(self):
        quote = KiteConnectClient._parse_quote({}, "RELIANCE", "NSE:RELIANCE")
        assert quote.symbol == "RELIANCE"
        assert quote.ltp == 0.0

    def test_non_dict(self):
        quote = KiteConnectClient._parse_quote("invalid", "RELIANCE", "NSE:RELIANCE")
        assert quote.symbol == "RELIANCE"


class TestProductMap:
    def test_cnc_maps(self):
        assert _PRODUCT_MAP["CNC"] == KITE_PRODUCT_CNC

    def test_intraday_maps_to_mis(self):
        assert _PRODUCT_MAP["INTRADAY"] == KITE_PRODUCT_MIS

    def test_mis_maps_to_mis(self):
        assert _PRODUCT_MAP["MIS"] == KITE_PRODUCT_MIS


@pytest.mark.asyncio
class TestKiteClientContextManager:
    async def test_aenter_creates_httpx_client(self, client):
        async with client as c:
            assert c._client is not None
        assert client._client is None

    async def test_aexit_closes_client(self, client):
        async with client:
            pass
        assert client._client is None


@pytest.mark.asyncio
class TestKiteClientRequest:
    async def test_request_without_init_raises(self, client):
        with pytest.raises(KiteBrokerError, match="not initialised"):
            await client._request("GET", "/test")

    async def test_request_success(self, client):
        async with client:
            # Mock the httpx client response
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"status": "success", "data": {"key": "value"}}
            client._client.request = AsyncMock(return_value=mock_resp)

            result = await client._request("GET", "/test")
            assert result == {"key": "value"}

    async def test_request_api_error(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "error",
                "message": "Invalid token",
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(KiteBrokerError, match="Invalid token"):
                await client._request("GET", "/test")

    async def test_request_http_error(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 403
            mock_resp.text = "Forbidden"
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(KiteBrokerError, match="API error 403"):
                await client._request("GET", "/test")


@pytest.mark.asyncio
class TestKiteClientQuote:
    async def test_get_quote(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "success",
                "data": {
                    "NSE:RELIANCE": {
                        "last_price": 2500.0,
                        "ohlc": {"open": 2490, "high": 2510, "low": 2480, "close": 2470},
                        "volume": 500000,
                        "net_change": 10.0,
                        "change": 0.4,
                        "depth": {"buy": [{"price": 2500}], "sell": [{"price": 2501}]},
                    }
                },
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            quote = await client.get_quote("NSE:RELIANCE", symbol="RELIANCE")
            assert quote.symbol == "RELIANCE"
            assert quote.ltp == 2500.0

    async def test_get_ltp(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "success",
                "data": {"NSE:RELIANCE": {"last_price": 2500.0}},
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            ltp = await client.get_ltp("RELIANCE")
            assert ltp == 2500.0


@pytest.mark.asyncio
class TestKiteClientOrders:
    async def test_place_order(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "success",
                "data": {"order_id": "220303000001234"},
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            order = OrderRequest(
                symbol="RELIANCE",
                side=Side.BUY,
                quantity=Decimal("10"),
                order_type=OrderType.LIMIT,
                price=2500.0,
                product=Product.CNC,
            )
            result = await client.place_order(order)
            assert result.order_id == "220303000001234"
            assert result.status == "PENDING"

            # Verify the request was made to correct endpoint
            call_args = client._client.request.call_args
            assert "/orders/regular" in call_args.args[1]

    async def test_place_amo_order(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "success",
                "data": {"order_id": "220303000001235"},
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            order = OrderRequest(
                symbol="RELIANCE",
                side=Side.BUY,
                quantity=Decimal("10"),
                order_type=OrderType.LIMIT,
                price=2500.0,
                is_amo=True,
            )
            result = await client.place_order(order)
            assert result.order_id == "220303000001235"

            # AMO orders use /orders/amo
            call_args = client._client.request.call_args
            assert "/orders/amo" in str(call_args)

    async def test_cancel_order(self, client):
        async with client:
            from skopaq.broker.models import CancelOrderRequest

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "success",
                "data": {"order_id": "220303000001234"},
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            req = CancelOrderRequest(order_id="220303000001234")
            result = await client.cancel_order(req)
            assert result.status == "CANCELLED"


@pytest.mark.asyncio
class TestKiteClientPortfolio:
    async def test_get_positions(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "success",
                "data": {
                    "net": [
                        {
                            "tradingsymbol": "RELIANCE",
                            "exchange": "NSE",
                            "product": "CNC",
                            "quantity": 10,
                            "average_price": 2450.0,
                            "last_price": 2500.0,
                            "pnl": 500.0,
                            "day_m2m": 100.0,
                            "buy_quantity": 10,
                            "sell_quantity": 0,
                            "buy_value": 24500.0,
                            "sell_value": 0.0,
                        }
                    ],
                    "day": [],
                },
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            positions = await client.get_positions()
            assert len(positions) == 1
            assert positions[0].symbol == "RELIANCE"
            assert positions[0].quantity == 10
            assert positions[0].average_price == 2450.0
            assert positions[0].pnl == 500.0

    async def test_get_holdings(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "success",
                "data": [
                    {
                        "tradingsymbol": "TCS",
                        "exchange": "NSE",
                        "quantity": 5,
                        "average_price": 3500.0,
                        "last_price": 3600.0,
                        "day_change": 50.0,
                        "day_change_percentage": 1.4,
                    }
                ],
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            holdings = await client.get_holdings()
            assert len(holdings) == 1
            assert holdings[0].symbol == "TCS"
            assert holdings[0].quantity == 5
            assert holdings[0].pnl == 500.0  # (3600-3500)*5

    async def test_get_funds(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "success",
                "data": {
                    "equity": {
                        "available": {
                            "live_balance": 500000.0,
                            "collateral": 100000.0,
                        },
                        "utilised": {"debits": 50000.0},
                    }
                },
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            funds = await client.get_funds()
            assert funds.available_cash == 500000.0
            assert funds.used_margin == 50000.0
            assert funds.total_collateral == 600000.0

    async def test_get_profile(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "status": "success",
                "data": {
                    "user_id": "AB1234",
                    "user_name": "Test User",
                    "email": "test@example.com",
                },
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            profile = await client.get_profile()
            assert profile.user_id == "AB1234"
            assert profile.name == "Test User"
            assert profile.broker == "Kite"


@pytest.mark.asyncio
class TestKiteClientHistorical:
    async def test_get_historical(self, client):
        async with client:
            # First mock: instruments CSV for token resolution
            instruments_resp = MagicMock()
            instruments_resp.status_code = 200
            instruments_resp.text = (
                "instrument_token,exchange_token,tradingsymbol,name,last_price,"
                "expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
                "738561,2885,RELIANCE,RELIANCE INDUSTRIES,2500.0,"
                ",,0.05,1,EQ,NSE,NSE\n"
            )

            # Second mock: historical data
            historical_resp = MagicMock()
            historical_resp.status_code = 200
            historical_resp.json.return_value = {
                "status": "success",
                "data": {
                    "candles": [
                        ["2024-01-15T09:15:00+0530", 2490, 2510, 2480, 2500, 500000],
                        ["2024-01-16T09:15:00+0530", 2500, 2520, 2490, 2510, 600000],
                    ]
                },
            }

            # Mock both calls in sequence
            client._client.request = AsyncMock(
                side_effect=[instruments_resp, historical_resp]
            )

            candles = await client.get_historical("NSE:RELIANCE", interval="1day")
            assert len(candles) == 2
            assert candles[0].open == 2490
            assert candles[0].close == 2500
            assert candles[0].volume == 500000

"""Tests for INDstocksClient — async REST client for INDstocks broker API.

All network calls are mocked via httpx mock responses.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from skopaq.broker.client import BrokerError, INDstocksClient
from skopaq.broker.models import (
    CancelOrderRequest,
    Funds,
    Holding,
    ModifyOrderRequest,
    OrderRequest,
    OrderResponse,
    Position,
    Quote,
    Side,
    UserProfile,
)


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.indstocks_base_url = "https://api.indstocks.com"
    return config


@pytest.fixture
def mock_token_mgr():
    mgr = MagicMock()
    mgr.get_token.return_value = "test-token-123"
    return mgr


@pytest.fixture
def client(mock_config, mock_token_mgr):
    return INDstocksClient(mock_config, mock_token_mgr)


# ── Init & Auth ──────────────────────────────────────────────────────────────


class TestInit:
    def test_creates_with_config(self, client):
        assert client._base_url == "https://api.indstocks.com"
        assert client._client is None

    def test_headers_no_bearer_prefix(self, client):
        headers = client._headers()
        assert headers["Authorization"] == "test-token-123"
        assert "Bearer" not in headers["Authorization"]

    def test_headers_raises_on_expired_token(self, mock_config):
        from skopaq.broker.token_manager import TokenExpiredError

        mgr = MagicMock()
        mgr.get_token.side_effect = TokenExpiredError("Token expired")
        c = INDstocksClient(mock_config, mgr)
        with pytest.raises(BrokerError):
            c._headers()


@pytest.mark.asyncio
class TestContextManager:
    async def test_aenter_creates_httpx_client(self, client):
        async with client as c:
            assert c._client is not None
        assert client._client is None

    async def test_aexit_closes_client(self, client):
        async with client:
            pass
        assert client._client is None


# ── _request ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRequest:
    async def test_request_without_init_raises(self, client):
        with pytest.raises(BrokerError, match="not initialised"):
            await client._request("GET", "/test")

    async def test_request_unwraps_data_key(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"status": "ok", "data": {"key": "val"}}
            client._client.request = AsyncMock(return_value=mock_resp)

            result = await client._request("GET", "/test")
            assert result == {"key": "val"}

    async def test_request_passes_through_no_data_key(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = [1, 2, 3]
            client._client.request = AsyncMock(return_value=mock_resp)

            result = await client._request("GET", "/test")
            assert result == [1, 2, 3]

    async def test_request_raises_on_4xx(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 403
            mock_resp.text = "Forbidden"
            client._client.request = AsyncMock(return_value=mock_resp)

            with pytest.raises(BrokerError, match="API error 403"):
                await client._request("GET", "/test")


# ── Market Data ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestMarketData:
    async def test_get_quote(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "data": {
                    "NSE_2885": {
                        "live_price": 2500.5,
                        "day_open": 2490.0,
                        "day_high": 2510.0,
                        "day_low": 2480.0,
                        "prev_close": 2470.0,
                        "volume": 1000000,
                        "day_change": 30.5,
                        "day_change_percentage": 1.23,
                        "best_bid_price": 2500.0,
                        "best_ask_price": 2501.0,
                    }
                }
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            quote = await client.get_quote("NSE_2885", symbol="RELIANCE")
            assert quote.symbol == "RELIANCE"
            assert quote.ltp == 2500.5
            assert quote.open == 2490.0
            assert quote.high == 2510.0
            assert quote.low == 2480.0
            assert quote.close == 2470.0
            assert quote.volume == 1000000
            assert quote.bid == 2500.0
            assert quote.ask == 2501.0

    async def test_get_ltp(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "data": {"NSE_2885": {"live_price": 2500.0}}
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            ltp = await client.get_ltp("NSE_2885")
            assert ltp == 2500.0

    async def test_get_quotes_batch(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "data": {
                    "NSE_2885": {"live_price": 2500.0, "day_open": 2490},
                    "NSE_11536": {"live_price": 3500.0, "day_open": 3490},
                }
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            quotes = await client.get_quotes(
                ["NSE_2885", "NSE_11536"],
                symbols=["RELIANCE", "TCS"],
            )
            assert len(quotes) == 2
            assert quotes[0].symbol == "RELIANCE"
            assert quotes[1].symbol == "TCS"

    async def test_get_historical(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "data": {
                    "NSE_2885": {
                        "candles": [
                            {"ts": 1740960000, "o": 2490, "h": 2510, "l": 2480, "c": 2500, "v": 500000},
                        ]
                    }
                }
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            candles = await client.get_historical("NSE_2885", interval="1day")
            assert len(candles) == 1
            assert candles[0].open == 2490
            assert candles[0].close == 2500
            assert candles[0].volume == 500000


# ── Orders ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestOrders:
    async def test_place_order(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "data": {"order_id": "ORD123", "status": "PENDING", "message": "OK"}
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            from decimal import Decimal
            order = OrderRequest(
                symbol="RELIANCE", side=Side.BUY, quantity=Decimal("10"),
                price=2500.0, security_id="2885",
            )
            result = await client.place_order(order)
            assert result.order_id == "ORD123"
            assert result.status == "PENDING"

            # Verify payload was sent correctly
            call_args = client._client.request.call_args
            assert call_args.kwargs["json"]["txn_type"] == "BUY"
            assert call_args.kwargs["json"]["qty"] == 10
            assert call_args.kwargs["json"]["security_id"] == "2885"
            assert call_args.kwargs["json"]["algo_id"] == "99999"

    async def test_cancel_order(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "data": {"order_id": "ORD123", "status": "CANCELLED"}
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            req = CancelOrderRequest(order_id="ORD123")
            result = await client.cancel_order(req)
            assert result.status == "CANCELLED"

    async def test_get_orders(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "data": [
                    {"order_id": "ORD1", "status": "COMPLETE", "message": "Filled"},
                    {"order_id": "ORD2", "status": "PENDING", "message": "Open"},
                ]
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            orders = await client.get_orders()
            assert len(orders) == 2
            assert orders[0].order_id == "ORD1"
            assert orders[0].status == "COMPLETE"
            assert isinstance(orders[0], OrderResponse)

    async def test_get_order_book(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "data": [{"order_id": "ORD1"}]
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            book = await client.get_order_book()
            assert len(book) == 1


# ── Portfolio ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPortfolio:
    async def test_get_positions(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "data": [
                    {
                        "symbol": "RELIANCE", "exchange": "NSE",
                        "net_qty": 10, "avg_price": 2450.0,
                        "last_price": 2500.0, "realized_profit": 500.0,
                    }
                ]
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            positions = await client.get_positions()
            assert len(positions) == 1
            assert positions[0].symbol == "RELIANCE"
            assert positions[0].quantity == 10
            assert positions[0].average_price == 2450.0

    async def test_get_holdings(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "data": [
                    {"symbol": "TCS", "exchange": "NSE", "quantity": 5, "average_price": 3500.0}
                ]
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            holdings = await client.get_holdings()
            assert len(holdings) == 1
            assert holdings[0].symbol == "TCS"

    async def test_get_funds(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "data": {
                    "detailed_avl_balance": {"eq_cnc": 500000.0},
                    "pledge_received": 100000.0,
                }
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            funds = await client.get_funds()
            assert funds.available_cash == 500000.0
            assert funds.total_collateral == 600000.0

    async def test_get_profile(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "data": {
                    "user_id": "USR123",
                    "name": "Test User",
                    "email": "test@example.com",
                }
            }
            client._client.request = AsyncMock(return_value=mock_resp)

            profile = await client.get_profile()
            assert profile.user_id == "USR123"
            assert profile.name == "Test User"
            assert profile.broker == "INDstocks"


# ── Error Handling ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestErrors:
    async def test_broker_error_fields(self):
        err = BrokerError("Test error", status_code=400, body='{"msg": "bad"}')
        assert str(err) == "Test error"
        assert err.status_code == 400
        assert err.body == '{"msg": "bad"}'

    async def test_empty_response_returns_defaults(self, client):
        async with client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"data": {}}
            client._client.request = AsyncMock(return_value=mock_resp)

            funds = await client.get_funds()
            assert funds.available_cash == 0.0

            positions = await client.get_positions()
            assert positions == []

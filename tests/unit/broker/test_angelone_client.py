"""Tests for Angel One SmartAPI client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skopaq.broker.angelone_client import AngelOneClient, AngelOneError


@pytest.fixture
def client():
    return AngelOneClient(
        api_key="test_api_key",
        client_id="TEST123",
        password="test_pass",
        totp_secret="",
    )


def _mock_login_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "status": True,
        "data": {"jwtToken": "jwt_token_123", "refreshToken": "refresh_123"},
    }
    return resp


class TestAngelOneInit:
    def test_creates_with_credentials(self, client):
        assert client._api_key == "test_api_key"
        assert client._client_id == "TEST123"
        assert client._client is None

    def test_headers_include_api_key(self, client):
        client._jwt_token = "test_jwt"
        headers = client._headers()
        assert headers["Authorization"] == "Bearer test_jwt"
        assert headers["X-PrivateKey"] == "test_api_key"


@pytest.mark.asyncio
class TestAngelOneLogin:
    async def test_login_stores_jwt(self, client):
        """Login should store JWT and refresh tokens."""
        # Manually create the httpx client (skip __aenter__ auto-login)
        import httpx
        client._client = httpx.AsyncClient(
            base_url="https://apiconnect.angelone.in", timeout=5,
        )
        try:
            client._client.request = AsyncMock(return_value=_mock_login_response())
            await client._login()

            assert client._jwt_token == "jwt_token_123"
            assert client._refresh_token == "refresh_123"
        finally:
            await client._client.aclose()
            client._client = None

    async def test_login_failure_raises(self, client):
        import httpx
        client._client = httpx.AsyncClient(
            base_url="https://apiconnect.angelone.in", timeout=5,
        )
        try:
            fail_resp = MagicMock()
            fail_resp.status_code = 200
            fail_resp.json.return_value = {
                "status": False,
                "message": "Invalid credentials",
            }
            client._client.request = AsyncMock(return_value=fail_resp)

            with pytest.raises(AngelOneError, match="Invalid credentials"):
                await client._login()
        finally:
            await client._client.aclose()
            client._client = None

    async def test_login_no_jwt_raises(self, client):
        import httpx
        client._client = httpx.AsyncClient(
            base_url="https://apiconnect.angelone.in", timeout=5,
        )
        try:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "status": True,
                "data": {},  # No jwtToken
            }
            client._client.request = AsyncMock(return_value=resp)

            with pytest.raises(AngelOneError, match="no JWT token"):
                await client._login()
        finally:
            await client._client.aclose()
            client._client = None


@pytest.mark.asyncio
class TestAngelOneQuote:
    async def _setup_client(self, client):
        """Helper: create httpx client and mock login."""
        import httpx
        client._client = httpx.AsyncClient(
            base_url="https://apiconnect.angelone.in", timeout=5,
        )
        client._jwt_token = "test_jwt"

    async def test_get_quote_parses_response(self, client):
        await self._setup_client(client)
        try:
            search_resp = MagicMock()
            search_resp.status_code = 200
            search_resp.json.return_value = {
                "status": True,
                "data": [{"tradingsymbol": "RELIANCE", "symboltoken": "2885"}],
            }

            quote_resp = MagicMock()
            quote_resp.status_code = 200
            quote_resp.json.return_value = {
                "status": True,
                "data": {
                    "fetched": [{
                        "ltp": 2500.0,
                        "open": 2490.0,
                        "high": 2510.0,
                        "low": 2480.0,
                        "close": 2470.0,
                        "tradeVolume": 1000000,
                        "netChange": 30.0,
                        "percentChange": 1.21,
                        "depth": {
                            "buy": [{"price": 2499.5, "quantity": 100}],
                            "sell": [{"price": 2500.5, "quantity": 50}],
                        },
                    }],
                },
            }

            client._client.request = AsyncMock(side_effect=[search_resp, quote_resp])

            quote = await client.get_quote("RELIANCE")
            assert quote.symbol == "RELIANCE"
            assert quote.ltp == 2500.0
            assert quote.bid == 2499.5
            assert quote.ask == 2500.5
            assert quote.volume == 1000000
        finally:
            await client._client.aclose()
            client._client = None

    async def test_get_ltp(self, client):
        await self._setup_client(client)
        try:
            search_resp = MagicMock()
            search_resp.status_code = 200
            search_resp.json.return_value = {
                "status": True,
                "data": [{"tradingsymbol": "TCS", "symboltoken": "11536"}],
            }

            ltp_resp = MagicMock()
            ltp_resp.status_code = 200
            ltp_resp.json.return_value = {
                "status": True,
                "data": {"fetched": [{"ltp": 3500.0}]},
            }

            client._client.request = AsyncMock(side_effect=[search_resp, ltp_resp])
            ltp = await client.get_ltp("TCS")
            assert ltp == 3500.0
        finally:
            await client._client.aclose()
            client._client = None

    async def test_empty_fetched_returns_default(self, client):
        await self._setup_client(client)
        try:
            search_resp = MagicMock()
            search_resp.status_code = 200
            search_resp.json.return_value = {
                "status": True,
                "data": [{"tradingsymbol": "X", "symboltoken": "999"}],
            }

            empty_resp = MagicMock()
            empty_resp.status_code = 200
            empty_resp.json.return_value = {
                "status": True,
                "data": {"fetched": []},
            }

            client._client.request = AsyncMock(side_effect=[search_resp, empty_resp])
            quote = await client.get_quote("X")
            assert quote.ltp == 0.0
        finally:
            await client._client.aclose()
            client._client = None


@pytest.mark.asyncio
class TestAngelOneRequest:
    async def test_http_error_raises(self, client):
        import httpx
        client._client = httpx.AsyncClient(
            base_url="https://apiconnect.angelone.in", timeout=5,
        )
        client._jwt_token = "jwt"
        try:
            resp = MagicMock()
            resp.status_code = 500
            resp.text = "Internal Server Error"
            client._client.request = AsyncMock(return_value=resp)

            with pytest.raises(AngelOneError, match="API error 500"):
                await client._request("POST", "/test")
        finally:
            await client._client.aclose()
            client._client = None


class TestSymbolCache:
    def test_cache_persists(self):
        AngelOneClient._symbol_cache["NSE:TEST"] = "12345"
        assert AngelOneClient._symbol_cache.get("NSE:TEST") == "12345"
        del AngelOneClient._symbol_cache["NSE:TEST"]


class TestAngelOneError:
    def test_fields(self):
        err = AngelOneError("Test", status_code=400)
        assert str(err) == "Test"
        assert err.status_code == 400

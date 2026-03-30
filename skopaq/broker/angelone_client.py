"""Angel One SmartAPI client for free real-time Indian market data.

Angel One provides free API access to all customers for NSE/BSE market data
including real-time quotes with actual bid/ask, 5-level market depth,
and historical OHLCV data.

Authentication: API key + client code + password + TOTP → JWT token.
Base URL: https://apiconnect.angelone.in

Usage::

    async with AngelOneClient(config) as client:
        quote = await client.get_quote("RELIANCE", "NSE")
        ltp = await client.get_ltp("RELIANCE", "NSE")

Setup:
    1. Open free Angel One demat account at angelone.com
    2. Generate API key at smartapi.angelbroking.com
    3. Set SKOPAQ_ANGELONE_API_KEY, SKOPAQ_ANGELONE_CLIENT_ID,
       SKOPAQ_ANGELONE_PASSWORD, SKOPAQ_ANGELONE_TOTP_SECRET in .env
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from skopaq.broker.models import HistoricalCandle, Quote
from skopaq.broker.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

_BASE_URL = "https://apiconnect.angelone.in"
_api_limiter = RateLimiter(max_calls=10, period=1.0)

# Angel One exchange segment mapping
_EXCHANGE_MAP = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "MCX": "MCX",
}


class AngelOneError(Exception):
    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


class AngelOneClient:
    """Async REST client for Angel One SmartAPI.

    Provides free real-time market data (quotes, LTP, depth) and
    historical OHLCV candles for NSE/BSE equities and F&O.

    Usage::

        async with AngelOneClient(config) as client:
            quote = await client.get_quote("RELIANCE", "NSE")
    """

    def __init__(
        self,
        api_key: str,
        client_id: str,
        password: str,
        totp_secret: str = "",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._client_id = client_id
        self._password = password
        self._totp_secret = totp_secret
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._jwt_token: str = ""
        self._refresh_token: str = ""

    async def __aenter__(self) -> AngelOneClient:
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=self._timeout,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        await self._login()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            # Attempt logout
            try:
                await self._request("POST", "/rest/secure/angelbroking/user/v1/logout", {
                    "clientcode": self._client_id,
                })
            except Exception:
                pass
            await self._client.aclose()
            self._client = None

    # ── Auth ─────────────────────────────────────────────────────────────

    async def _login(self) -> None:
        """Authenticate and obtain JWT token.

        Endpoint: POST /rest/secure/angelbroking/user/v1/loginByPassword
        """
        totp = self._generate_totp() if self._totp_secret else ""

        body = {
            "clientcode": self._client_id,
            "password": self._password,
        }
        if totp:
            body["totp"] = totp

        data = await self._request_public(
            "POST",
            "/rest/secure/angelbroking/user/v1/loginByPassword",
            body,
        )

        self._jwt_token = data.get("jwtToken", "")
        self._refresh_token = data.get("refreshToken", "")

        if not self._jwt_token:
            raise AngelOneError("Login failed: no JWT token returned")

        logger.info("Angel One login successful for client %s", self._client_id)

    def _generate_totp(self) -> str:
        """Generate TOTP code from secret."""
        try:
            import pyotp
            return pyotp.TOTP(self._totp_secret).now()
        except ImportError:
            logger.warning("pyotp not installed — TOTP generation skipped")
            return ""

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._jwt_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": self._api_key,
        }

    # ── Request helpers ──────────────────────────────────────────────────

    async def _request_public(
        self, method: str, path: str, body: dict,
    ) -> dict:
        """Send unauthenticated request (login only)."""
        if self._client is None:
            raise AngelOneError("Client not initialised")

        await _api_limiter.acquire()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": self._api_key,
        }
        try:
            resp = await self._client.request(
                method, path, headers=headers, json=body,
            )
        except httpx.HTTPError as exc:
            raise AngelOneError(f"HTTP error: {exc}") from exc

        if resp.status_code >= 400:
            raise AngelOneError(
                f"API error {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
            )

        result = resp.json()
        if not result.get("status"):
            raise AngelOneError(result.get("message", "Request failed"))

        return result.get("data", {})

    async def _request(
        self, method: str, path: str, body: Optional[dict] = None,
    ) -> Any:
        """Send authenticated request."""
        if self._client is None:
            raise AngelOneError("Client not initialised")

        await _api_limiter.acquire()
        try:
            resp = await self._client.request(
                method, path,
                headers=self._headers(),
                json=body or {},
            )
        except httpx.HTTPError as exc:
            raise AngelOneError(f"HTTP error: {exc}") from exc

        if resp.status_code >= 400:
            raise AngelOneError(
                f"API error {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
            )

        result = resp.json()
        if not result.get("status"):
            raise AngelOneError(result.get("message", "Request failed"))

        return result.get("data", {})

    # ── Market Data ──────────────────────────────────────────────────────

    async def get_quote(self, symbol: str, exchange: str = "NSE") -> Quote:
        """Fetch full quote with real bid/ask and market depth.

        Endpoint: POST /rest/secure/angelbroking/market/v1/quote/
        """
        # Angel One uses symboltoken (numeric) for API calls.
        # For simplicity, we use the search endpoint to resolve first.
        token = await self._resolve_symbol_token(symbol, exchange)

        data = await self._request(
            "POST",
            "/rest/secure/angelbroking/market/v1/quote/",
            {
                "mode": "FULL",
                "exchangeTokens": {
                    exchange: [token],
                },
            },
        )

        # Response: {"fetched": [{"exchange": "NSE", "tradingSymbol": "RELIANCE", ...}]}
        fetched = data.get("fetched", [])
        if not fetched:
            return Quote(symbol=symbol, exchange=exchange)

        q = fetched[0]
        return Quote(
            symbol=symbol,
            exchange=exchange,
            ltp=float(q.get("ltp", 0)),
            open=float(q.get("open", 0)),
            high=float(q.get("high", 0)),
            low=float(q.get("low", 0)),
            close=float(q.get("close", 0)),
            volume=int(q.get("tradeVolume", 0)),
            change=float(q.get("netChange", 0)),
            change_pct=float(q.get("percentChange", 0)),
            bid=float(q.get("depth", {}).get("buy", [{}])[0].get("price", 0)),
            ask=float(q.get("depth", {}).get("sell", [{}])[0].get("price", 0)),
            timestamp=datetime.now(timezone.utc),
        )

    async def get_ltp(self, symbol: str, exchange: str = "NSE") -> float:
        """Fetch just the last traded price.

        Endpoint: POST /rest/secure/angelbroking/market/v1/quote/
        Uses LTP mode for minimal data transfer.
        """
        token = await self._resolve_symbol_token(symbol, exchange)

        data = await self._request(
            "POST",
            "/rest/secure/angelbroking/market/v1/quote/",
            {
                "mode": "LTP",
                "exchangeTokens": {
                    exchange: [token],
                },
            },
        )

        fetched = data.get("fetched", [])
        if fetched:
            return float(fetched[0].get("ltp", 0))
        return 0.0

    async def get_historical(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "ONE_DAY",
        from_date: str = "",
        to_date: str = "",
    ) -> list[HistoricalCandle]:
        """Fetch historical OHLCV candles.

        Endpoint: POST /rest/secure/angelbroking/historical/v1/getCandleData

        Args:
            interval: ONE_MINUTE, FIVE_MINUTE, FIFTEEN_MINUTE, THIRTY_MINUTE,
                      ONE_HOUR, ONE_DAY
        """
        token = await self._resolve_symbol_token(symbol, exchange)

        if not from_date:
            from datetime import timedelta
            from_date = (datetime.now() - timedelta(days=365)).strftime(
                "%Y-%m-%d %H:%M"
            )
        if not to_date:
            to_date = datetime.now().strftime("%Y-%m-%d %H:%M")

        data = await self._request(
            "POST",
            "/rest/secure/angelbroking/historical/v1/getCandleData",
            {
                "exchange": exchange,
                "symboltoken": token,
                "interval": interval,
                "fromdate": from_date,
                "todate": to_date,
            },
        )

        candles = []
        for row in data if isinstance(data, list) else []:
            # [timestamp, open, high, low, close, volume]
            if isinstance(row, list) and len(row) >= 6:
                try:
                    dt = datetime.fromisoformat(str(row[0]))
                except (ValueError, TypeError):
                    dt = datetime.now()
                candles.append(HistoricalCandle(
                    timestamp=dt,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=int(row[5]),
                ))
        return candles

    # ── Symbol resolution ────────────────────────────────────────────────

    _symbol_cache: dict[str, str] = {}  # class-level cache

    async def _resolve_symbol_token(self, symbol: str, exchange: str = "NSE") -> str:
        """Resolve a tradingsymbol to Angel One's numeric symboltoken.

        Endpoint: POST /rest/secure/angelbroking/order/v1/searchScrip
        """
        cache_key = f"{exchange}:{symbol}"
        if cache_key in self._symbol_cache:
            return self._symbol_cache[cache_key]

        data = await self._request(
            "POST",
            "/rest/secure/angelbroking/order/v1/searchScrip",
            {"exchange": exchange, "searchscrip": symbol},
        )

        results = data if isinstance(data, list) else []
        for item in results:
            if item.get("tradingsymbol", "").upper() == symbol.upper():
                token = str(item.get("symboltoken", ""))
                self._symbol_cache[cache_key] = token
                return token

        # Fallback: use first result if exact match not found
        if results:
            token = str(results[0].get("symboltoken", ""))
            self._symbol_cache[cache_key] = token
            return token

        raise AngelOneError(f"Cannot resolve symbol token for {symbol} on {exchange}")

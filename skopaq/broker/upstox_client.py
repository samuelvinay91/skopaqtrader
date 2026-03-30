"""Upstox API v2 client for free real-time Indian market data.

Upstox provides free API access for NSE/BSE market data including
real-time quotes with bid/ask, market depth, and historical OHLCV.

Authentication: OAuth2 → access_token (valid for 1 day).
Base URL: https://api.upstox.com/v2

Usage::

    async with UpstoxClient(access_token) as client:
        quote = await client.get_quote("RELIANCE", "NSE_EQ")
        ltp = await client.get_ltp("RELIANCE", "NSE_EQ")

Setup:
    1. Open free Upstox demat account at upstox.com
    2. Create app at upstox.com/developer/apps → get API key + secret
    3. Complete OAuth2 login → get access_token
    4. Set SKOPAQ_UPSTOX_ACCESS_TOKEN in .env
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from skopaq.broker.models import HistoricalCandle, Quote
from skopaq.broker.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.upstox.com/v2"
_api_limiter = RateLimiter(max_calls=25, period=1.0)

# Upstox instrument key format: EXCHANGE_SEGMENT|TRADINGSYMBOL
# e.g., NSE_EQ|INE002A01018 (ISIN-based) or NSE_EQ|RELIANCE
_EXCHANGE_SEGMENT_MAP = {
    "NSE": "NSE_EQ",
    "BSE": "BSE_EQ",
    "NFO": "NSE_FO",
    "MCX": "MCX_FO",
}


class UpstoxError(Exception):
    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


class UpstoxClient:
    """Async REST client for Upstox API v2.

    Provides free real-time market data (quotes, LTP, depth) and
    historical OHLCV candles for NSE/BSE equities.

    Usage::

        async with UpstoxClient(access_token) as client:
            quote = await client.get_quote("RELIANCE")
    """

    def __init__(
        self,
        access_token: str,
        timeout: float = 30.0,
    ) -> None:
        self._access_token = access_token
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        # Cache: {symbol: instrument_key}
        self._instrument_cache: dict[str, str] = {}

    async def __aenter__(self) -> UpstoxClient:
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=self._timeout,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Request helper ───────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }

    async def _request(
        self, method: str, path: str,
        params: Optional[dict[str, str]] = None,
        body: Optional[dict] = None,
    ) -> Any:
        """Send authenticated request to Upstox API v2."""
        if self._client is None:
            raise UpstoxError("Client not initialised")

        await _api_limiter.acquire()

        try:
            resp = await self._client.request(
                method, path,
                headers=self._headers(),
                params=params,
                json=body,
            )
        except httpx.HTTPError as exc:
            raise UpstoxError(f"HTTP error: {exc}") from exc

        if resp.status_code >= 400:
            raise UpstoxError(
                f"API error {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
            )

        result = resp.json()
        if result.get("status") == "error":
            errors = result.get("errors", [{}])
            msg = errors[0].get("message", "Unknown error") if errors else "Unknown error"
            raise UpstoxError(msg)

        return result.get("data", {})

    # ── Market Data ──────────────────────────────────────────────────────

    async def get_quote(self, symbol: str, exchange: str = "NSE") -> Quote:
        """Fetch full quote with real bid/ask.

        Endpoint: GET /market-quote/quotes?instrument_key=NSE_EQ|RELIANCE
        """
        instrument_key = self._build_instrument_key(symbol, exchange)

        data = await self._request(
            "GET", "/market-quote/quotes",
            params={"instrument_key": instrument_key},
        )

        # Response: {"NSE_EQ:RELIANCE": {"ohlc": {...}, "depth": {...}, ...}}
        if not isinstance(data, dict):
            return Quote(symbol=symbol, exchange=exchange)

        # Data is keyed by instrument_key format
        quote_data = None
        for key, val in data.items():
            quote_data = val
            break

        if not quote_data:
            return Quote(symbol=symbol, exchange=exchange)

        ohlc = quote_data.get("ohlc", {})
        depth = quote_data.get("depth", {})
        buy_depth = depth.get("buy", [{}])
        sell_depth = depth.get("sell", [{}])

        ltp = float(quote_data.get("last_price", 0))
        prev_close = float(ohlc.get("close", 0))
        change = ltp - prev_close if prev_close else 0.0
        change_pct = (change / prev_close * 100) if prev_close else 0.0

        return Quote(
            symbol=symbol,
            exchange=exchange,
            ltp=ltp,
            open=float(ohlc.get("open", 0)),
            high=float(ohlc.get("high", 0)),
            low=float(ohlc.get("low", 0)),
            close=prev_close,
            volume=int(quote_data.get("volume", 0)),
            change=round(change, 2),
            change_pct=round(change_pct, 2),
            bid=float(buy_depth[0].get("price", 0)) if buy_depth else 0.0,
            ask=float(sell_depth[0].get("price", 0)) if sell_depth else 0.0,
            timestamp=datetime.now(timezone.utc),
        )

    async def get_ltp(self, symbol: str, exchange: str = "NSE") -> float:
        """Fetch just the last traded price.

        Endpoint: GET /market-quote/ltp?instrument_key=NSE_EQ|RELIANCE
        """
        instrument_key = self._build_instrument_key(symbol, exchange)

        data = await self._request(
            "GET", "/market-quote/ltp",
            params={"instrument_key": instrument_key},
        )

        if isinstance(data, dict):
            for key, val in data.items():
                return float(val.get("last_price", 0))
        return 0.0

    async def get_historical(
        self,
        symbol: str,
        exchange: str = "NSE",
        interval: str = "day",
        from_date: str = "",
        to_date: str = "",
    ) -> list[HistoricalCandle]:
        """Fetch historical OHLCV candles.

        Endpoint: GET /historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}

        Args:
            interval: 1minute, 5minute, 15minute, 30minute, day, week, month
        """
        instrument_key = self._build_instrument_key(symbol, exchange)

        if not to_date:
            to_date = datetime.now().strftime("%Y-%m-%d")
        if not from_date:
            from_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        data = await self._request(
            "GET",
            f"/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}",
        )

        candles_raw = data.get("candles", []) if isinstance(data, dict) else []
        candles = []
        for row in candles_raw:
            # [timestamp, open, high, low, close, volume, oi]
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

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _build_instrument_key(symbol: str, exchange: str = "NSE") -> str:
        """Build Upstox instrument key from symbol and exchange.

        Format: NSE_EQ|RELIANCE
        """
        segment = _EXCHANGE_SEGMENT_MAP.get(exchange.upper(), "NSE_EQ")
        return f"{segment}|{symbol.upper()}"

    @staticmethod
    def get_login_url(api_key: str, redirect_uri: str) -> str:
        """Return the Upstox OAuth2 login URL.

        After login, Upstox redirects to redirect_uri with ?code=xxx.
        Exchange the code for access_token via POST /login/authorization/token.
        """
        return (
            f"https://api.upstox.com/v2/login/authorization/dialog"
            f"?client_id={api_key}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
        )

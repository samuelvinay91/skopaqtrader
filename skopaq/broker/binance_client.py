"""Async REST client for Binance public market data.

Uses unauthenticated endpoints only — no API key required.
Rate limit: 1200 weight/minute (each ticker call = 1 weight).

Endpoints:
    GET /api/v3/ticker/24hr?symbol=BTCUSDT   → full 24h stats
    GET /api/v3/ticker/price?symbol=BTCUSDT   → last price only
    GET /api/v3/exchangeInfo?symbol=BTCUSDT   → lot size, tick size
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from skopaq.broker.models import Exchange, Quote

logger = logging.getLogger(__name__)

DEFAULT_BINANCE_BASE_URL = "https://api.binance.com"
_TIMEOUT = 10.0  # seconds


class BinanceError(Exception):
    """Raised when a Binance API call fails."""

    def __init__(self, message: str, status_code: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class BinanceClient:
    """Public market data from the Binance REST API.

    No API key needed — uses unauthenticated endpoints only.
    Designed for paper trading: read-only quote fetching.

    Usage::

        async with BinanceClient() as client:
            quote = await client.get_quote("BTCUSDT")
            print(quote.ltp)
    """

    def __init__(self, base_url: str = DEFAULT_BINANCE_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> BinanceClient:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=_TIMEOUT,
            headers={"Accept": "application/json"},
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Public API ────────────────────────────────────────────────────

    async def get_quote(self, symbol: str) -> Quote:
        """Fetch 24-hour ticker statistics for a symbol.

        Args:
            symbol: Binance pair symbol (e.g., "BTCUSDT").

        Returns:
            Quote model populated from Binance 24hr ticker data.

        Raises:
            BinanceError: On API error or invalid symbol.
        """
        data = await self._get("/api/v3/ticker/24hr", params={"symbol": symbol.upper()})
        return self._to_quote(data, symbol)

    async def get_price(self, symbol: str) -> float:
        """Fetch the current price for a symbol.

        Args:
            symbol: Binance pair symbol (e.g., "BTCUSDT").

        Returns:
            Last traded price as float.
        """
        data = await self._get("/api/v3/ticker/price", params={"symbol": symbol.upper()})
        return float(data["price"])

    async def get_exchange_info(self, symbol: str) -> dict[str, Any]:
        """Fetch exchange info for a symbol (lot size, tick size, filters).

        Args:
            symbol: Binance pair symbol (e.g., "BTCUSDT").

        Returns:
            Dict with symbol info including filters for lot size, min notional, etc.
        """
        data = await self._get(
            "/api/v3/exchangeInfo",
            params={"symbol": symbol.upper()},
        )
        symbols = data.get("symbols", [])
        if not symbols:
            raise BinanceError(f"No exchange info for {symbol}", status_code=404)
        return symbols[0]

    # ── Internal ──────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """Execute a GET request against the Binance API."""
        if self._client is None:
            raise RuntimeError("BinanceClient must be used as async context manager")

        resp = await self._client.get(path, params=params)

        # Log rate-limit weight usage if header present
        used_weight = resp.headers.get("X-MBX-USED-WEIGHT-1M")
        if used_weight:
            weight = int(used_weight)
            if weight > 1000:
                logger.warning("Binance rate limit weight: %d/1200", weight)

        if resp.status_code != 200:
            body = resp.text[:500]
            raise BinanceError(
                f"Binance API error {resp.status_code}: {body}",
                status_code=resp.status_code,
                body=body,
            )

        return resp.json()

    @staticmethod
    def _to_quote(data: dict[str, Any], symbol: str) -> Quote:
        """Convert Binance 24hr ticker JSON to our Quote model.

        Binance field mapping:
            lastPrice         → ltp
            openPrice         → open
            highPrice         → high
            lowPrice          → low
            prevClosePrice    → close
            volume            → volume
            bidPrice          → bid
            askPrice          → ask
            priceChange       → change
            priceChangePercent → change_pct
        """
        return Quote(
            symbol=symbol.upper(),
            exchange=Exchange.BINANCE,
            ltp=float(data.get("lastPrice", 0)),
            open=float(data.get("openPrice", 0)),
            high=float(data.get("highPrice", 0)),
            low=float(data.get("lowPrice", 0)),
            close=float(data.get("prevClosePrice", 0)),
            volume=int(float(data.get("volume", 0))),
            change=float(data.get("priceChange", 0)),
            change_pct=float(data.get("priceChangePercent", 0)),
            bid=float(data.get("bidPrice", 0)),
            ask=float(data.get("askPrice", 0)),
            timestamp=datetime.now(timezone.utc),
        )

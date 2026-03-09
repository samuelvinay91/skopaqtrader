"""Authenticated Binance client for live crypto trading.

Supports:
    - Spot trading (order placement, cancellation, modification)
    - Account balance queries
    - Order book access
    - Trade history

Usage::

    client = BinanceAuthClient(
        api_key="your_api_key",
        api_secret="your_api_secret"
    )
    await client.place_order(symbol="BTCUSDT", side="BUY", quantity=0.001)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import httpx

from skopaq.broker.models import Exchange, OrderResponse, OrderStatus, Quote, Side

logger = logging.getLogger(__name__)

DEFAULT_BINANCE_BASE_URL = "https://api.binance.com"
DEFAULT_BINANCE_TEST_URL = "https://testnet.binance.vision"


class BinanceAuthError(Exception):
    """Raised when a Binance authenticated API call fails."""

    def __init__(self, message: str, code: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.body = body


class BinanceAuthClient:
    """Authenticated Binance API client for live trading.

    Requires API key and secret with spot trading permissions.
    Supports both production and testnet URLs.

    Usage::

        async with BinanceAuthClient(api_key="...", api_secret="...") as client:
            balance = await client.get_balance("USDT")
            await client.place_order("BTCUSDT", "BUY", 0.001, 50000.0)
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = DEFAULT_BINANCE_BASE_URL,
        testnet: bool = False,
    ) -> None:
        if testnet:
            base_url = DEFAULT_BINANCE_TEST_URL

        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_secret = api_secret
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> BinanceAuthClient:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=30.0,
            headers={
                "Accept": "application/json",
                "X-MBX-APIKEY": self._api_key,
            },
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _sign(self, params: dict[str, str]) -> str:
        """Generate HMAC SHA256 signature for request."""
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        signature = hmac.new(
            self._api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        signed: bool = False,
    ) -> dict[str, Any]:
        """Execute authenticated request to Binance API."""
        if self._client is None:
            raise RuntimeError("BinanceAuthClient must be used as async context manager")

        params = params or {}
        params["timestamp"] = str(int(time.time() * 1000))

        if signed:
            params["signature"] = self._sign(params)

        url = f"/api/v3/{endpoint}"
        resp = await self._client.request(method, url, data=params if signed else None)

        if resp.status_code != 200:
            try:
                error = resp.json()
                code = error.get("code", 0)
                msg = error.get("msg", resp.text)
            except Exception:
                code = resp.status_code
                msg = resp.text[:500]
            raise BinanceAuthError(f"Binance API error: {msg}", code=code, body=msg)

        return resp.json()

    async def get_balance(self, asset: str = "USDT") -> dict[str, Any]:
        """Get account balance for a specific asset.

        Args:
            asset: Currency symbol (e.g., "USDT", "BTC", "ETH")

        Returns:
            Dict with free, locked, and total balance.
        """
        data = await self._request("GET", "account", signed=True)
        balances = {b["asset"]: b for b in data.get("balances", [])}
        return balances.get(asset, {"asset": asset, "free": "0", "locked": "0"})

    async def get_all_balances(self) -> list[dict[str, Any]]:
        """Get all account balances."""
        data = await self._request("GET", "account", signed=True)
        return [
            {
                "asset": b["asset"],
                "free": Decimal(b["free"]),
                "locked": Decimal(b["locked"]),
            }
            for b in data.get("balances", [])
            if Decimal(b["free"]) > 0 or Decimal(b["locked"]) > 0
        ]

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: str = "LIMIT",
        time_in_force: str = "GTC",
    ) -> dict[str, Any]:
        """Place a spot order.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            side: "BUY" or "SELL"
            quantity: Order quantity
            price: Limit price (required for LIMIT orders)
            order_type: "LIMIT", "MARKET", "STOP_LOSS", "STOP_LOSS_LIMIT"
            time_in_force: "GTC", "IOC", "FOK"

        Returns:
            Order response with orderId, status, etc.
        """
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": str(quantity),
            "timeInForce": time_in_force,
        }

        if price:
            params["price"] = str(price)
            params["quoteOrderQty"] = str(quantity * price)
        elif order_type.upper() == "MARKET":
            params.pop("timeInForce", None)

        return await self._request("POST", "order", params=params, signed=True)

    async def cancel_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        """Cancel an active order.

        Args:
            symbol: Trading pair
            order_id: Binance order ID

        Returns:
            Cancellation confirmation.
        """
        params = {"symbol": symbol.upper(), "orderId": str(order_id)}
        return await self._request("DELETE", "order", params=params, signed=True)

    async def get_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        """Get order status and details.

        Args:
            symbol: Trading pair
            order_id: Binance order ID

        Returns:
            Full order details.
        """
        params = {"symbol": symbol.upper(), "orderId": str(order_id)}
        return await self._request("GET", "order", params=params, signed=True)

    async def get_open_orders(self, symbol: Optional[str] = None) -> list[dict[str, Any]]:
        """Get all open orders.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of open orders.
        """
        params = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return await self._request("GET", "openOrders", params=params, signed=True)

    async def get_order_history(
        self, symbol: Optional[str] = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Get historical orders.

        Args:
            symbol: Optional symbol filter
            limit: Max results (default 500, max 1000)

        Returns:
            List of past orders.
        """
        params = {"limit": str(limit)}
        if symbol:
            params["symbol"] = symbol.upper()
        return await self._request("GET", "allOrders", params=params, signed=True)

    async def get_my_trades(self, symbol: str, limit: int = 500) -> list[dict[str, Any]]:
        """Get trade history for a symbol.

        Args:
            symbol: Trading pair
            limit: Max results

        Returns:
            List of executed trades.
        """
        params = {"symbol": symbol.upper(), "limit": str(limit)}
        return await self._request("GET", "myTrades", params=params, signed=True)

    async def get_depth(self, symbol: str, limit: int = 100) -> dict[str, Any]:
        """Get order book depth.

        Args:
            symbol: Trading pair
            limit: Depth levels (5, 10, 20, 50, 100, 500, 1000, 5000)

        Returns:
            Order book with bids and asks.
        """
        params = {"symbol": symbol.upper(), "limit": str(limit)}
        return await self._request("GET", "depth", params=params)

    async def get_ticker_24h(self, symbol: str) -> Quote:
        """Get 24-hour ticker statistics.

        Args:
            symbol: Trading pair

        Returns:
            Quote model with 24h stats.
        """
        data = await self._request("GET", "ticker/24hr", params={"symbol": symbol.upper()})
        return self._to_quote(data)

    @staticmethod
    def _to_quote(data: dict[str, Any]) -> Quote:
        """Convert Binance 24hr ticker to Quote model."""
        return Quote(
            symbol=data.get("symbol", ""),
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


class BinanceTestClient(BinanceAuthClient):
    """Binance testnet client for paper trading with real exchange behavior.

    Uses Binance Testnet (testnet.binance.vision) which simulates
    the full trading experience without real money.
    """

    def __init__(self, api_key: str, api_secret: str) -> None:
        super().__init__(
            api_key=api_key,
            api_secret=api_secret,
            base_url=DEFAULT_BINANCE_TEST_URL,
            testnet=True,
        )

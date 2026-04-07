"""Zerodha Kite Connect broker client.

Wraps the ``kiteconnect`` SDK to match the same interface used by
``INDstocksClient`` — so the ``OrderRouter`` can switch between
brokers transparently.

OAuth login flow:
    1. User visits ``/api/kite/login`` → redirected to Zerodha login
    2. After login, Zerodha redirects to ``/api/kite/callback?request_token=XXX``
    3. Callback exchanges request_token for access_token
    4. Access token stored in memory (valid for one trading day)

Usage::

    from skopaq.broker.kite_client import KiteClient

    client = KiteClient(api_key="...", api_secret="...", access_token="...")
    quote = client.get_quote("NSE:TCS")
    positions = client.get_positions()
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from kiteconnect import KiteConnect

from skopaq.broker.models import (
    ExecutionResult,
    Funds,
    Holding,
    OrderRequest,
    OrderResponse,
    Position,
    Quote,
    Side,
)

logger = logging.getLogger(__name__)

# Module-level access token cache
_access_token: str = ""

# Persistent storage: /data on Fly.io (volume mount), /tmp locally
import os as _os
_DATA_DIR = "/data" if _os.path.isdir("/data") else "/tmp"
_TOKEN_FILE = _os.path.join(_DATA_DIR, "skopaq_kite_token.json")


def set_access_token(token: str) -> None:
    """Set the Kite access token and persist to file + env var."""
    global _access_token
    _access_token = token

    # Persist to file so it survives module reloads
    import json
    from datetime import datetime, timezone

    try:
        with open(_TOKEN_FILE, "w") as f:
            json.dump({
                "access_token": token,
                "set_at": datetime.now(timezone.utc).isoformat(),
            }, f)
        logger.info("Kite access token set and persisted")
    except Exception as exc:
        logger.warning("Could not persist Kite token: %s", exc)

    # Also set as env var for subprocess access
    import os
    os.environ["SKOPAQ_KITE_ACCESS_TOKEN"] = token


def get_access_token() -> str:
    """Get the current access token.

    Priority:
    1. Module-level cache (fastest)
    2. Persisted file (/tmp/skopaq_kite_token.json)
    3. SKOPAQ_KITE_ACCESS_TOKEN env var
    4. SkopaqConfig (from .env)
    """
    global _access_token
    if _access_token:
        return _access_token

    # Try persisted file
    import json

    try:
        with open(_TOKEN_FILE) as f:
            data = json.load(f)
            token = data.get("access_token", "")
            if token:
                _access_token = token
                logger.info("Kite token restored from file")
                return token
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Try env var
    import os

    env_token = os.environ.get("SKOPAQ_KITE_ACCESS_TOKEN", "")
    if env_token:
        _access_token = env_token
        logger.info("Kite token restored from env var")
        return env_token

    # Try config
    try:
        from skopaq.config import SkopaqConfig

        config = SkopaqConfig()
        cfg_token = config.kite_access_token.get_secret_value()
        if cfg_token:
            _access_token = cfg_token
            return cfg_token
    except Exception:
        pass

    # Try fetching from the API server (for Telegram bot running on separate machine)
    try:
        import httpx

        resp = httpx.get("https://skopaq-trader.fly.dev/api/kite/token", timeout=5)
        if resp.status_code == 200:
            token = resp.json().get("access_token", "")
            if token:
                _access_token = token
                # Persist locally so we don't keep fetching
                set_access_token(token)
                logger.info("Kite token fetched from API server")
                return token
    except Exception:
        pass

    return ""


class KiteClient:
    """Zerodha Kite Connect client matching INDstocksClient interface."""

    def __init__(
        self,
        api_key: str,
        api_secret: str = "",
        access_token: str = "",
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._kite = KiteConnect(api_key=api_key)

        if access_token:
            self._kite.set_access_token(access_token)

    def set_access_token(self, token: str) -> None:
        """Set access token (call after OAuth flow)."""
        self._kite.set_access_token(token)
        set_access_token(token)

    def generate_session(self, request_token: str) -> dict:
        """Exchange request_token for access_token."""
        data = self._kite.generate_session(
            request_token, api_secret=self._api_secret
        )
        self._kite.set_access_token(data["access_token"])
        set_access_token(data["access_token"])
        logger.info("Kite session generated for %s", data.get("user_id", "?"))
        return data

    @property
    def login_url(self) -> str:
        """Get the Kite login URL for OAuth."""
        return self._kite.login_url()

    # ── Market Data ──────────────────────────────────────────────────────

    async def get_quote(self, scrip_code: str, symbol: str = "") -> Quote:
        """Get real-time quote. ``scrip_code`` is ``NSE:TCS`` format."""
        import asyncio

        data = await asyncio.to_thread(
            self._kite.quote, [scrip_code]
        )
        q = data.get(scrip_code, {})
        ohlc = q.get("ohlc", {})

        return Quote(
            symbol=symbol or scrip_code.split(":")[-1],
            exchange=scrip_code.split(":")[0] if ":" in scrip_code else "NSE",
            ltp=q.get("last_price", 0),
            open=ohlc.get("open", 0),
            high=ohlc.get("high", 0),
            low=ohlc.get("low", 0),
            close=ohlc.get("close", 0),
            volume=q.get("volume", 0),
            change=q.get("net_change", 0),
            change_pct=round(
                (q.get("net_change", 0) / ohlc.get("close", 1)) * 100, 2
            ) if ohlc.get("close") else 0,
            bid=q.get("depth", {}).get("buy", [{}])[0].get("price", 0) if q.get("depth") else 0,
            ask=q.get("depth", {}).get("sell", [{}])[0].get("price", 0) if q.get("depth") else 0,
        )

    async def get_positions(self) -> list[Position]:
        """Get open positions."""
        import asyncio

        data = await asyncio.to_thread(self._kite.positions)
        positions = []
        for p in data.get("net", []):
            if p.get("quantity", 0) != 0:
                positions.append(Position(
                    symbol=p.get("tradingsymbol", ""),
                    exchange=p.get("exchange", ""),
                    product=p.get("product", ""),
                    quantity=Decimal(str(p.get("quantity", 0))),
                    average_price=p.get("average_price", 0),
                    last_price=p.get("last_price", 0),
                    pnl=p.get("pnl", 0),
                    day_pnl=p.get("day_m2m", 0),
                ))
        return positions

    async def get_holdings(self) -> list[Holding]:
        """Get delivery holdings."""
        import asyncio

        data = await asyncio.to_thread(self._kite.holdings)
        return [
            Holding(
                symbol=h.get("tradingsymbol", ""),
                exchange=h.get("exchange", ""),
                quantity=Decimal(str(h.get("quantity", 0))),
                average_price=h.get("average_price", 0),
                last_price=h.get("last_price", 0),
                pnl=h.get("pnl", 0),
                day_change=h.get("day_change", 0),
                day_change_pct=h.get("day_change_percentage", 0),
            )
            for h in data
        ]

    async def get_funds(self) -> Funds:
        """Get available margins/funds."""
        import asyncio

        data = await asyncio.to_thread(self._kite.margins)
        equity = data.get("equity", {})
        return Funds(
            available_cash=equity.get("available", {}).get("cash", 0),
            used_margin=equity.get("utilised", {}).get("debits", 0),
            available_margin=equity.get("net", 0),
            total_collateral=equity.get("available", {}).get("collateral", 0),
        )

    async def get_order_book(self) -> list[dict]:
        """Get today's orders."""
        import asyncio

        orders = await asyncio.to_thread(self._kite.orders)
        return orders or []

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """Place an order via Kite Connect."""
        import asyncio

        # Map our order types to Kite's
        variety = "regular"
        order_type = order.order_type.value
        if order_type == "SL-M":
            order_type = "SL-M"
            variety = "regular"

        try:
            order_id = await asyncio.to_thread(
                self._kite.place_order,
                variety=variety,
                exchange=order.exchange.value,
                tradingsymbol=order.symbol,
                transaction_type=order.side.value,
                quantity=int(order.quantity),
                product=order.product.value,
                order_type=order_type,
                price=order.price if order.price else None,
                trigger_price=order.trigger_price if order.trigger_price else None,
            )
            logger.info("Kite order placed: %s", order_id)
            return OrderResponse(
                order_id=str(order_id),
                status="PENDING",
                message=f"Order placed via Kite Connect",
            )
        except Exception as exc:
            logger.error("Kite order failed: %s", exc)
            return OrderResponse(
                order_id="",
                status="FAILED",
                message=str(exc),
            )

    # ── Context manager (compatibility with INDstocksClient) ─────────

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

"""WebSocket clients for INDstocks real-time price feed and order updates.

Two persistent connections:
  1. **Price feed** — streams LTP/bid/ask for subscribed symbols (max 100).
  2. **Order updates** — pushes order status changes in real-time.

Both auto-reconnect with exponential backoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine, Optional

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatusCode

from skopaq.broker.models import Exchange, OrderResponse, OrderStatus, Quote
from skopaq.broker.token_manager import TokenExpiredError, TokenManager

logger = logging.getLogger(__name__)

# Reconnect parameters
INITIAL_BACKOFF_S = 1.0
MAX_BACKOFF_S = 60.0
BACKOFF_MULTIPLIER = 2.0

# Type alias for callbacks
QuoteCallback = Callable[[Quote], Coroutine[Any, Any, None]]
OrderCallback = Callable[[OrderResponse], Coroutine[Any, Any, None]]


class PriceFeed:
    """WebSocket client for real-time price updates.

    Subscribes to up to 100 symbols and invokes a callback for each tick.

    Args:
        ws_url: WebSocket URL for price feed.
        token_manager: Provides the Bearer token for auth.
        on_quote: Async callback invoked with each Quote update.
    """

    def __init__(
        self,
        ws_url: str,
        token_manager: TokenManager,
        on_quote: QuoteCallback,
    ) -> None:
        self._ws_url = ws_url
        self._token_manager = token_manager
        self._on_quote = on_quote
        self._subscribed: set[str] = set()
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        """Start the price feed connection loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._connection_loop())
        logger.info("Price feed started")

    async def stop(self) -> None:
        """Gracefully stop the price feed."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Price feed stopped")

    async def subscribe(self, symbols: list[str], exchange: Exchange = Exchange.NSE) -> None:
        """Subscribe to price updates for given symbols."""
        for s in symbols:
            self._subscribed.add(f"{exchange.value}:{s}")

        if self._ws:
            await self._send_subscribe()

    async def unsubscribe(self, symbols: list[str], exchange: Exchange = Exchange.NSE) -> None:
        """Unsubscribe from symbols."""
        for s in symbols:
            self._subscribed.discard(f"{exchange.value}:{s}")

        if self._ws:
            await self._send_unsubscribe(symbols, exchange)

    async def _connection_loop(self) -> None:
        """Connect and reconnect with exponential backoff."""
        backoff = INITIAL_BACKOFF_S

        while self._running:
            try:
                token = self._token_manager.get_token()
                headers = {"Authorization": f"Bearer {token}"}

                async with websockets.connect(
                    self._ws_url,
                    additional_headers=headers,
                    ping_interval=30,
                    ping_timeout=10,
                ) as ws:
                    self._ws = ws
                    backoff = INITIAL_BACKOFF_S  # Reset on successful connect
                    logger.info("Price feed connected")

                    # Re-subscribe to symbols
                    if self._subscribed:
                        await self._send_subscribe()

                    # Message loop
                    async for raw in ws:
                        try:
                            data = json.loads(raw)
                            await self._handle_message(data)
                        except json.JSONDecodeError:
                            logger.warning("Invalid JSON from price feed: %s", raw[:200])

            except TokenExpiredError:
                logger.error("Token expired — price feed cannot reconnect")
                break
            except (ConnectionClosed, InvalidStatusCode, OSError) as exc:
                if not self._running:
                    break
                logger.warning("Price feed disconnected: %s. Reconnecting in %.1fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_S)
            except Exception:
                if not self._running:
                    break
                logger.exception("Unexpected price feed error. Reconnecting in %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_S)
            finally:
                self._ws = None

    async def _send_subscribe(self) -> None:
        """Send subscription message for all tracked symbols."""
        if not self._ws or not self._subscribed:
            return
        msg = json.dumps({
            "action": "subscribe",
            "symbols": list(self._subscribed),
        })
        await self._ws.send(msg)
        logger.debug("Subscribed to %d symbols", len(self._subscribed))

    async def _send_unsubscribe(self, symbols: list[str], exchange: Exchange) -> None:
        """Send unsubscribe message."""
        if not self._ws:
            return
        keys = [f"{exchange.value}:{s}" for s in symbols]
        msg = json.dumps({"action": "unsubscribe", "symbols": keys})
        await self._ws.send(msg)

    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Parse a price tick and invoke callback."""
        # Expected format: {"symbol": "RELIANCE", "exchange": "NSE", "ltp": 2500.50, ...}
        if "symbol" not in data:
            return

        quote = Quote(
            symbol=data["symbol"],
            exchange=Exchange(data.get("exchange", "NSE")),
            ltp=float(data.get("ltp", 0)),
            open=float(data.get("open", 0)),
            high=float(data.get("high", 0)),
            low=float(data.get("low", 0)),
            close=float(data.get("close", 0)),
            volume=int(data.get("volume", 0)),
            bid=float(data.get("bid", 0)),
            ask=float(data.get("ask", 0)),
        )
        await self._on_quote(quote)


class OrderUpdateFeed:
    """WebSocket client for real-time order status updates.

    Args:
        ws_url: WebSocket URL for order updates.
        token_manager: Provides the Bearer token for auth.
        on_order: Async callback invoked with each OrderResponse update.
    """

    def __init__(
        self,
        ws_url: str,
        token_manager: TokenManager,
        on_order: OrderCallback,
    ) -> None:
        self._ws_url = ws_url
        self._token_manager = token_manager
        self._on_order = on_order
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        """Start the order update feed."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._connection_loop())
        logger.info("Order update feed started")

    async def stop(self) -> None:
        """Gracefully stop the order update feed."""
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Order update feed stopped")

    async def _connection_loop(self) -> None:
        """Connect and reconnect with exponential backoff."""
        backoff = INITIAL_BACKOFF_S

        while self._running:
            try:
                token = self._token_manager.get_token()
                headers = {"Authorization": f"Bearer {token}"}

                async with websockets.connect(
                    self._ws_url,
                    additional_headers=headers,
                    ping_interval=30,
                    ping_timeout=10,
                ) as ws:
                    self._ws = ws
                    backoff = INITIAL_BACKOFF_S
                    logger.info("Order update feed connected")

                    async for raw in ws:
                        try:
                            data = json.loads(raw)
                            await self._handle_message(data)
                        except json.JSONDecodeError:
                            logger.warning("Invalid JSON from order feed: %s", raw[:200])

            except TokenExpiredError:
                logger.error("Token expired — order feed cannot reconnect")
                break
            except (ConnectionClosed, InvalidStatusCode, OSError) as exc:
                if not self._running:
                    break
                logger.warning("Order feed disconnected: %s. Reconnecting in %.1fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_S)
            except Exception:
                if not self._running:
                    break
                logger.exception("Unexpected order feed error. Reconnecting in %.1fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_S)
            finally:
                self._ws = None

    async def _handle_message(self, data: dict[str, Any]) -> None:
        """Parse an order update and invoke callback."""
        if "order_id" not in data:
            return

        order = OrderResponse(
            order_id=str(data["order_id"]),
            status=OrderStatus(data.get("status", "PENDING")),
            message=data.get("message", ""),
            exchange_order_id=data.get("exchange_order_id"),
        )
        await self._on_order(order)

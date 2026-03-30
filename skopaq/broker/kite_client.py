"""Async REST client for the Kite Connect (Zerodha) broker API.

Wraps the ``kiteconnect`` Python SDK in an async interface that matches
the same model types used by ``INDstocksClient`` (Quote, Position, Holding,
Funds, OrderRequest, OrderResponse, etc.) so the OrderRouter can dispatch
to either broker transparently.

Key differences from INDstocks:
    - Auth: ``api_key`` + ``access_token`` (OAuth2 flow, valid ~6 AM to 6 AM)
    - Orders: ``variety`` param (regular/amo/co/iceberg), ``exchange`` per call
    - Instruments: ``instrument_token`` (numeric) + ``tradingsymbol``
    - Historical: datetime objects, intervals like "minute", "day", "5minute"
    - Positions: day vs net positions
    - Product types: CNC, MIS, NRML (native, no translation needed)

Usage::

    async with KiteConnectClient(config, token_mgr) as client:
        quote = await client.get_quote("NSE:RELIANCE")
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from functools import partial
from typing import Any, Optional

import httpx

from skopaq.broker.kite_token_manager import KiteTokenExpiredError, KiteTokenManager
from skopaq.broker.models import (
    CancelOrderRequest,
    Funds,
    HistoricalCandle,
    Holding,
    ModifyOrderRequest,
    OrderRequest,
    OrderResponse,
    Position,
    Quote,
    UserProfile,
)
from skopaq.broker.rate_limiter import RateLimiter
from skopaq.config import SkopaqConfig

logger = logging.getLogger(__name__)

# Kite Connect rate limits: 10 orders/sec, 10 requests/sec for historical
_api_limiter = RateLimiter(max_calls=10, period=1.0)
_order_limiter = RateLimiter(max_calls=10, period=1.0)

# Kite Connect exchange strings
KITE_EXCHANGE_NSE = "NSE"
KITE_EXCHANGE_BSE = "BSE"
KITE_EXCHANGE_NFO = "NFO"
KITE_EXCHANGE_BFO = "BFO"
KITE_EXCHANGE_MCX = "MCX"
KITE_EXCHANGE_CDS = "CDS"

# Kite Connect product types
KITE_PRODUCT_CNC = "CNC"       # Cash and Carry (delivery)
KITE_PRODUCT_MIS = "MIS"       # Intraday
KITE_PRODUCT_NRML = "NRML"     # Normal (F&O)

# Kite Connect order types
KITE_ORDER_MARKET = "MARKET"
KITE_ORDER_LIMIT = "LIMIT"
KITE_ORDER_SL = "SL"
KITE_ORDER_SLM = "SL-M"

# Kite Connect variety types
KITE_VARIETY_REGULAR = "regular"
KITE_VARIETY_AMO = "amo"
KITE_VARIETY_CO = "co"
KITE_VARIETY_ICEBERG = "iceberg"

# Product mapping from internal to Kite
_PRODUCT_MAP = {
    "CNC": KITE_PRODUCT_CNC,
    "INTRADAY": KITE_PRODUCT_MIS,
    "MARGIN": KITE_PRODUCT_NRML,
    "MIS": KITE_PRODUCT_MIS,
    "NRML": KITE_PRODUCT_NRML,
}


class KiteBrokerError(Exception):
    """Raised when a Kite Connect API call fails."""

    def __init__(self, message: str, status_code: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class KiteConnectClient:
    """Async HTTP client for Kite Connect REST API.

    The Kite Connect API is synchronous (REST/JSON), so we wrap all calls
    in ``asyncio.to_thread`` for non-blocking execution.  This avoids
    pulling in the full ``kiteconnect`` SDK as a hard dependency — we use
    plain ``httpx`` instead.

    Usage::

        async with KiteConnectClient(config, token_mgr) as client:
            quote = await client.get_quote("NSE:RELIANCE")
    """

    BASE_URL = "https://api.kite.trade"

    def __init__(
        self,
        config: SkopaqConfig,
        token_manager: KiteTokenManager,
        *,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = config.kite_api_key.get_secret_value()
        self._token_manager = token_manager
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        # Instrument cache: {tradingsymbol: instrument_token}
        self._instruments: dict[str, int] = {}
        self._instruments_loaded: bool = False

    async def __aenter__(self) -> KiteConnectClient:
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=self._timeout,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Internal helpers ─────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        """Build Kite Connect auth headers.

        Kite uses ``Authorization: token api_key:access_token``.
        """
        try:
            access_token = self._token_manager.get_token()
        except KiteTokenExpiredError as exc:
            raise KiteBrokerError(str(exc)) from exc
        return {
            "Authorization": f"token {self._api_key}:{access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Kite-Version": "3",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        form_data: Optional[dict[str, Any]] = None,
        is_order: bool = False,
    ) -> Any:
        """Send an API request with rate limiting and error handling.

        Kite Connect returns JSON: ``{"status": "success", "data": {...}}``
        or ``{"status": "error", "message": "...", "error_type": "..."}``
        """
        if self._client is None:
            raise KiteBrokerError(
                "Client not initialised. Use `async with` context manager."
            )

        limiter = _order_limiter if is_order else _api_limiter
        await limiter.acquire()

        try:
            if form_data is not None:
                resp = await self._client.request(
                    method,
                    path,
                    headers=self._headers(),
                    params=params,
                    data=form_data,
                )
            else:
                resp = await self._client.request(
                    method,
                    path,
                    headers=self._headers(),
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise KiteBrokerError(f"HTTP error: {exc}") from exc

        if resp.status_code >= 400:
            raise KiteBrokerError(
                f"API error {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
                body=resp.text,
            )

        data = resp.json()

        # Kite wraps responses in {"status": "success"|"error", "data": ...}
        if isinstance(data, dict):
            if data.get("status") == "error":
                raise KiteBrokerError(
                    data.get("message", "Unknown Kite API error"),
                    body=str(data),
                )
            if "data" in data:
                return data["data"]
        return data

    # ── Market Data ──────────────────────────────────────────────────────

    async def get_quote(self, scrip_code: str, symbol: str = "") -> Quote:
        """Fetch full quote for a symbol.

        Args:
            scrip_code: Kite instrument key like ``NSE:RELIANCE``.
                For compatibility with INDstocksClient signature, also accepts
                plain symbols (resolved to ``NSE:{symbol}``).
            symbol: Optional human-readable name for the returned Quote.

        Endpoint: ``GET /quote?i=NSE:RELIANCE``
        """
        instrument_key = self._normalize_instrument_key(scrip_code)
        data = await self._request(
            "GET", "/quote",
            params={"i": instrument_key},
        )

        if isinstance(data, dict):
            quote_data = data.get(instrument_key, {})
            return self._parse_quote(quote_data, symbol or scrip_code, instrument_key)

        return Quote(symbol=symbol or scrip_code)

    async def get_quotes(
        self, scrip_codes: list[str], symbols: list[str] | None = None,
    ) -> list[Quote]:
        """Fetch full quotes for multiple symbols.

        Endpoint: ``GET /quote?i=NSE:RELIANCE&i=NSE:TCS``
        """
        instrument_keys = [self._normalize_instrument_key(sc) for sc in scrip_codes]
        # Kite accepts multiple `i` params
        params_list = [("i", k) for k in instrument_keys]

        # Use raw httpx for multi-value params
        if self._client is None:
            raise KiteBrokerError("Client not initialised.")

        await _api_limiter.acquire()
        try:
            resp = await self._client.request(
                "GET", "/quote",
                headers=self._headers(),
                params=params_list,
            )
        except httpx.HTTPError as exc:
            raise KiteBrokerError(f"HTTP error: {exc}") from exc

        if resp.status_code >= 400:
            raise KiteBrokerError(
                f"API error {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
                body=resp.text,
            )

        result = resp.json()
        data = result.get("data", result) if isinstance(result, dict) else {}

        quotes: list[Quote] = []
        for i, key in enumerate(instrument_keys):
            qd = data.get(key, {})
            sym = symbols[i] if symbols and i < len(symbols) else scrip_codes[i]
            quotes.append(self._parse_quote(qd, sym, key))
        return quotes

    async def get_ltp(self, scrip_code: str) -> float:
        """Fetch just the last traded price.

        Endpoint: ``GET /quote/ltp?i=NSE:RELIANCE``
        """
        instrument_key = self._normalize_instrument_key(scrip_code)
        data = await self._request(
            "GET", "/quote/ltp",
            params={"i": instrument_key},
        )

        if isinstance(data, dict):
            ltp_data = data.get(instrument_key, {})
            if isinstance(ltp_data, dict):
                return float(ltp_data.get("last_price", 0))
        return 0.0

    async def get_historical(
        self,
        scrip_code: str,
        interval: str = "1day",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> list[HistoricalCandle]:
        """Fetch OHLCV candles.

        Endpoint: ``GET /instruments/historical/{instrument_token}/{interval}``

        Args:
            scrip_code: Kite instrument key (``NSE:RELIANCE``) or instrument token.
            interval: Candle interval — maps from INDstocks-style intervals:
                ``1day`` → ``day``, ``1minute`` → ``minute``, ``5minute`` → ``5minute``
            start_time: Unix epoch milliseconds (converted to ``YYYY-MM-DD HH:MM:SS``).
            end_time: Unix epoch milliseconds (converted to ``YYYY-MM-DD HH:MM:SS``).
        """
        # Resolve instrument token
        instrument_token = await self._resolve_instrument_token(scrip_code)
        kite_interval = self._map_interval(interval)

        # Convert epoch ms to datetime strings
        if start_time is not None:
            from_dt = datetime.fromtimestamp(start_time / 1000).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        else:
            from_dt = (datetime.now() - timedelta(days=365)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        if end_time is not None:
            to_dt = datetime.fromtimestamp(end_time / 1000).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        else:
            to_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        data = await self._request(
            "GET",
            f"/instruments/historical/{instrument_token}/{kite_interval}",
            params={"from": from_dt, "to": to_dt},
        )

        candles: list[HistoricalCandle] = []
        # Kite returns {"candles": [[ts, o, h, l, c, v], ...]}
        raw_candles = data.get("candles", []) if isinstance(data, dict) else []
        for row in raw_candles:
            if isinstance(row, list) and len(row) >= 6:
                # row[0] is ISO timestamp string like "2024-01-15T09:15:00+0530"
                ts = row[0]
                if isinstance(ts, str):
                    dt = datetime.fromisoformat(ts)
                else:
                    dt = datetime.fromtimestamp(int(ts))
                candles.append(
                    HistoricalCandle(
                        timestamp=dt,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=int(row[5]),
                    )
                )
        return candles

    async def get_instruments(self, source: str = "equity") -> str:
        """Fetch instruments master as CSV text.

        Endpoint: ``GET /instruments`` or ``GET /instruments/NSE``

        Returns raw CSV with columns:
        instrument_token, exchange_token, tradingsymbol, name, last_price,
        expiry, strike, tick_size, lot_size, instrument_type, segment, exchange
        """
        exchange = "NSE" if source == "equity" else source.upper()
        if self._client is None:
            raise KiteBrokerError("Client not initialised.")

        await _api_limiter.acquire()
        try:
            resp = await self._client.request(
                "GET",
                f"/instruments/{exchange}",
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise KiteBrokerError(f"HTTP error: {exc}") from exc

        if resp.status_code >= 400:
            raise KiteBrokerError(
                f"API error {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.text

    # ── Orders ───────────────────────────────────────────────────────────

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """Place a new order.

        Endpoint: ``POST /orders/{variety}``

        Translates internal field names to Kite API names:
            symbol         → tradingsymbol
            side           → transaction_type
            quantity        → quantity
            price          → price
            order_type     → order_type
            product        → product
        """
        variety = KITE_VARIETY_AMO if order.is_amo else KITE_VARIETY_REGULAR
        product = _PRODUCT_MAP.get(order.product.value, KITE_PRODUCT_CNC)

        payload: dict[str, Any] = {
            "tradingsymbol": order.symbol,
            "exchange": order.exchange.value,
            "transaction_type": order.side.value,
            "order_type": order.order_type.value,
            "quantity": int(order.quantity),
            "product": product,
            "validity": order.validity.value,
        }
        if order.price is not None:
            payload["price"] = order.price
        if order.trigger_price is not None:
            payload["trigger_price"] = order.trigger_price
        if order.disclosed_quantity > 0:
            payload["disclosed_quantity"] = order.disclosed_quantity

        data = await self._request(
            "POST",
            f"/orders/{variety}",
            form_data=payload,
            is_order=True,
        )
        logger.info(
            "Order placed: %s %s qty=%d via Kite Connect",
            order.side,
            order.symbol,
            order.quantity,
        )

        if isinstance(data, dict):
            return OrderResponse(
                order_id=str(data.get("order_id", "")),
                status="PENDING",
                message="Order placed successfully",
            )
        return OrderResponse(
            order_id=str(data) if data else "",
            status="PENDING",
            message="Order placed",
        )

    async def modify_order(self, req: ModifyOrderRequest) -> OrderResponse:
        """Modify a pending order.

        Endpoint: ``PUT /orders/{variety}/{order_id}``
        """
        payload: dict[str, Any] = {}
        if req.quantity is not None:
            payload["quantity"] = req.quantity
        if req.price is not None:
            payload["price"] = req.price
        if req.order_type is not None:
            payload["order_type"] = req.order_type.value

        data = await self._request(
            "PUT",
            f"/orders/regular/{req.order_id}",
            form_data=payload,
            is_order=True,
        )
        if isinstance(data, dict):
            return OrderResponse(
                order_id=str(data.get("order_id", req.order_id)),
                status="PENDING",
                message="Order modified",
            )
        return OrderResponse(order_id=req.order_id, status="PENDING", message="Modified")

    async def cancel_order(self, req: CancelOrderRequest) -> OrderResponse:
        """Cancel a pending order.

        Endpoint: ``DELETE /orders/{variety}/{order_id}``
        """
        data = await self._request(
            "DELETE",
            f"/orders/regular/{req.order_id}",
            is_order=True,
        )
        if isinstance(data, dict):
            return OrderResponse(
                order_id=str(data.get("order_id", req.order_id)),
                status="CANCELLED",
                message="Order cancelled",
            )
        return OrderResponse(
            order_id=req.order_id, status="CANCELLED", message="Cancelled"
        )

    async def get_order_book(self) -> list[dict[str, Any]]:
        """Fetch all orders for the day.

        Endpoint: ``GET /orders``
        """
        data = await self._request("GET", "/orders")
        if isinstance(data, list):
            return data
        return []

    async def get_orders(self) -> list[OrderResponse]:
        """Fetch today's orders as OrderResponse models."""
        raw_orders = await self.get_order_book()
        return [
            OrderResponse(
                order_id=str(o.get("order_id", "")),
                status=str(o.get("status", "")),
                message=str(o.get("status_message", "")),
                exchange_order_id=o.get("exchange_order_id"),
            )
            for o in raw_orders
        ]

    async def get_trades(self, order_id: str) -> list[dict[str, Any]]:
        """Fetch trades for an order.

        Endpoint: ``GET /orders/{order_id}/trades``
        """
        data = await self._request("GET", f"/orders/{order_id}/trades")
        if isinstance(data, list):
            return data
        return []

    async def get_trade_book(self, segment: str = "EQUITY") -> list[dict[str, Any]]:
        """Fetch all trades.

        Endpoint: ``GET /trades``
        """
        data = await self._request("GET", "/trades")
        if isinstance(data, list):
            return data
        return []

    # ── Portfolio ─────────────────────────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        """Fetch current positions (net + day).

        Endpoint: ``GET /portfolio/positions``

        Kite returns ``{"net": [...], "day": [...]}``.  We use net positions
        to match INDstocksClient behaviour.
        """
        data = await self._request("GET", "/portfolio/positions")
        positions: list[Position] = []

        if isinstance(data, dict):
            net_positions = data.get("net", [])
        elif isinstance(data, list):
            net_positions = data
        else:
            net_positions = []

        for p in net_positions:
            if not isinstance(p, dict):
                continue
            positions.append(
                Position(
                    symbol=p.get("tradingsymbol", ""),
                    exchange=p.get("exchange", ""),
                    product=p.get("product", ""),
                    quantity=p.get("quantity", 0),
                    average_price=float(p.get("average_price", 0)),
                    last_price=float(p.get("last_price", 0)),
                    pnl=float(p.get("pnl", 0)),
                    day_pnl=float(p.get("day_m2m", 0)),
                    buy_quantity=p.get("buy_quantity", 0),
                    sell_quantity=p.get("sell_quantity", 0),
                    buy_value=float(p.get("buy_value", 0)),
                    sell_value=float(p.get("sell_value", 0)),
                )
            )
        return positions

    async def get_holdings(self) -> list[Holding]:
        """Fetch delivery holdings.

        Endpoint: ``GET /portfolio/holdings``
        """
        data = await self._request("GET", "/portfolio/holdings")
        holdings: list[Holding] = []

        raw = data if isinstance(data, list) else []
        for h in raw:
            if not isinstance(h, dict):
                continue
            avg_price = float(h.get("average_price", 0))
            last_price = float(h.get("last_price", 0))
            qty = int(h.get("quantity", 0))
            pnl = (last_price - avg_price) * qty if avg_price > 0 else 0
            day_change = float(h.get("day_change", 0))
            day_change_pct = float(h.get("day_change_percentage", 0))

            holdings.append(
                Holding(
                    symbol=h.get("tradingsymbol", ""),
                    exchange=h.get("exchange", ""),
                    quantity=qty,
                    average_price=avg_price,
                    last_price=last_price,
                    pnl=pnl,
                    day_change=day_change,
                    day_change_pct=day_change_pct,
                )
            )
        return holdings

    async def get_funds(self) -> Funds:
        """Fetch available funds and margin.

        Endpoint: ``GET /user/margins``

        Kite returns margins per segment: ``{"equity": {...}, "commodity": {...}}``.
        """
        data = await self._request("GET", "/user/margins")
        if isinstance(data, dict):
            equity = data.get("equity", {})
            available = float(equity.get("available", {}).get("live_balance", 0))
            used = float(equity.get("utilised", {}).get("debits", 0))
            collateral = float(
                equity.get("available", {}).get("collateral", 0)
            )

            return Funds(
                available_cash=available,
                available_margin=available,
                used_margin=used,
                total_collateral=available + collateral,
            )
        return Funds()

    # ── User ─────────────────────────────────────────────────────────────

    async def get_profile(self) -> UserProfile:
        """Fetch authenticated user's profile.

        Endpoint: ``GET /user/profile``
        """
        data = await self._request("GET", "/user/profile")
        if isinstance(data, dict):
            return UserProfile(
                user_id=data.get("user_id", ""),
                name=data.get("user_name", ""),
                email=data.get("email", ""),
                broker="Kite",
            )
        return UserProfile(broker="Kite")

    # ── Instrument Resolution ─────────────────────────────────────────────

    async def _load_instruments(self) -> None:
        """Load and cache NSE instrument tokens from Kite instruments API."""
        if self._instruments_loaded:
            return

        try:
            csv_text = await self.get_instruments("equity")
            lines = csv_text.strip().split("\n")
            if len(lines) < 2:
                return

            # Parse header to find column indices
            header = lines[0].split(",")
            try:
                token_idx = header.index("instrument_token")
                symbol_idx = header.index("tradingsymbol")
                exchange_idx = header.index("exchange")
            except ValueError:
                logger.warning("Unexpected Kite instruments CSV header: %s", header[:5])
                return

            for line in lines[1:]:
                cols = line.split(",")
                if len(cols) > max(token_idx, symbol_idx, exchange_idx):
                    exchange = cols[exchange_idx].strip()
                    symbol = cols[symbol_idx].strip()
                    try:
                        token = int(cols[token_idx].strip())
                        self._instruments[f"{exchange}:{symbol}"] = token
                    except ValueError:
                        continue

            self._instruments_loaded = True
            logger.info(
                "Loaded %d Kite instruments", len(self._instruments)
            )
        except Exception:
            logger.warning("Failed to load Kite instruments", exc_info=True)

    async def _resolve_instrument_token(self, scrip_code: str) -> int:
        """Resolve a symbol to its Kite instrument token.

        Args:
            scrip_code: Either ``NSE:RELIANCE``, plain ``RELIANCE``,
                or a numeric instrument token string.
        """
        # If already numeric, return directly
        try:
            return int(scrip_code)
        except ValueError:
            pass

        instrument_key = self._normalize_instrument_key(scrip_code)

        # Check cache
        if instrument_key in self._instruments:
            return self._instruments[instrument_key]

        # Load instruments if not yet loaded
        await self._load_instruments()

        if instrument_key in self._instruments:
            return self._instruments[instrument_key]

        raise KiteBrokerError(
            f"Cannot resolve instrument token for '{scrip_code}'. "
            "Ensure the symbol exists on NSE."
        )

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_instrument_key(scrip_code: str) -> str:
        """Normalize a symbol to ``EXCHANGE:SYMBOL`` format.

        Examples:
            ``RELIANCE``       → ``NSE:RELIANCE``
            ``NSE:RELIANCE``   → ``NSE:RELIANCE``
            ``NSE_2885``       → ``NSE:NSE_2885`` (INDstocks format, best-effort)
        """
        if ":" in scrip_code:
            return scrip_code
        return f"NSE:{scrip_code}"

    @staticmethod
    def _parse_quote(
        quote_data: dict[str, Any], symbol: str, instrument_key: str
    ) -> Quote:
        """Parse a Kite quote response into our Quote model.

        Kite quote fields:
            last_price, ohlc.open, ohlc.high, ohlc.low, ohlc.close,
            volume, net_change, change (%), depth.buy[0].price, depth.sell[0].price
        """
        if not isinstance(quote_data, dict):
            return Quote(symbol=symbol)

        ohlc = quote_data.get("ohlc", {})
        depth = quote_data.get("depth", {})
        buy_depth = depth.get("buy", [{}])
        sell_depth = depth.get("sell", [{}])

        exchange = instrument_key.split(":")[0] if ":" in instrument_key else "NSE"

        return Quote(
            symbol=symbol,
            exchange=exchange,
            ltp=float(quote_data.get("last_price", 0)),
            open=float(ohlc.get("open", 0)),
            high=float(ohlc.get("high", 0)),
            low=float(ohlc.get("low", 0)),
            close=float(ohlc.get("close", 0)),
            volume=int(quote_data.get("volume", 0)),
            change=float(quote_data.get("net_change", 0)),
            change_pct=float(quote_data.get("change", 0)),
            bid=float(buy_depth[0].get("price", 0)) if buy_depth else 0.0,
            ask=float(sell_depth[0].get("price", 0)) if sell_depth else 0.0,
        )

    @staticmethod
    def _map_interval(interval: str) -> str:
        """Map INDstocks-style interval to Kite interval.

        INDstocks: 1day, 1week, 1month, 1minute, 5minute, 15minute, 30minute, 60minute
        Kite:      day, week, month, minute, 5minute, 15minute, 30minute, 60minute
        """
        mapping = {
            "1day": "day",
            "1week": "week",
            "1month": "month",
            "1minute": "minute",
            "1second": "minute",  # Kite doesn't support 1s, fallback
        }
        return mapping.get(interval, interval)

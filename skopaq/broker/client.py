"""Async REST client for the INDstocks broker API.

Endpoint paths, auth headers, and field names are taken directly from
live API testing — do NOT modify without testing against real API first.

Key differences from typical broker APIs:
    - Auth header: ``Authorization: TOKEN`` (NO "Bearer " prefix)
    - No ``/api/v1/`` path prefix — paths start at root
    - Orders require ``algo_id="99999"`` for regular orders
    - ALL market data endpoints use ``scrip-codes=NSE_2885`` param format
      (exchange underscore security_id from instruments CSV)
    - Historical candles are objects: ``{"ts": epoch_sec, "o":, "h":, ...}``
    - Quote response fields: ``live_price``, ``day_open``, ``day_high``,
      ``day_low``, ``prev_close``, ``day_change``, ``day_change_percentage``
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import httpx

from skopaq.broker.models import (
    CancelOrderRequest,
    Funds,
    HistoricalCandle,
    Holding,
    ModifyOrderRequest,
    OptionChain,
    OptionData,
    OrderRequest,
    OrderResponse,
    Position,
    Quote,
    Segment,
    UserProfile,
)
from skopaq.broker.rate_limiter import RateLimiter
from skopaq.broker.token_manager import TokenExpiredError, TokenManager
from skopaq.config import SkopaqConfig

logger = logging.getLogger(__name__)

# Separate limiters matching INDstocks rate limits
_api_limiter = RateLimiter(max_calls=100, period=1.0)
_order_limiter = RateLimiter(max_calls=10, period=1.0)


class BrokerError(Exception):
    """Raised when a broker API call fails."""

    def __init__(self, message: str, status_code: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class INDstocksClient:
    """Async HTTP client for INDstocks REST API.

    Usage::

        async with INDstocksClient(config, token_mgr) as client:
            quote = await client.get_quote("NSE_2885", symbol="RELIANCE")
    """

    def __init__(
        self,
        config: SkopaqConfig,
        token_manager: TokenManager,
        *,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = config.indstocks_base_url.rstrip("/")
        self._token_manager = token_manager
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> INDstocksClient:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
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
        """Build auth headers.

        INDstocks uses ``Authorization: TOKEN`` — NO "Bearer " prefix.
        """
        try:
            token = self._token_manager.get_token()
        except TokenExpiredError as exc:
            raise BrokerError(str(exc)) from exc
        return {
            "Authorization": token,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        is_order: bool = False,
    ) -> Any:
        """Send an API request with rate limiting and error handling.

        Returns the parsed JSON response. If the response has a
        ``{"data": ...}`` wrapper, returns the inner ``data`` value.
        """
        if self._client is None:
            raise BrokerError("Client not initialised. Use `async with` context manager.")

        limiter = _order_limiter if is_order else _api_limiter
        await limiter.acquire()

        try:
            resp = await self._client.request(
                method,
                path,
                headers=self._headers(),
                params=params,
                json=json_body,
            )
        except httpx.HTTPError as exc:
            raise BrokerError(f"HTTP error: {exc}") from exc

        if resp.status_code >= 400:
            raise BrokerError(
                f"API error {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
                body=resp.text,
            )

        data = resp.json()

        # INDstocks wraps some responses in {"status": ..., "data": {...}}
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    async def _request_text(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
    ) -> str:
        """Send a request expecting text/CSV response (instruments endpoint)."""
        if self._client is None:
            raise BrokerError("Client not initialised. Use `async with` context manager.")

        await _api_limiter.acquire()

        try:
            resp = await self._client.request(
                method, path, headers=self._headers(), params=params,
            )
        except httpx.HTTPError as exc:
            raise BrokerError(f"HTTP error: {exc}") from exc

        if resp.status_code >= 400:
            raise BrokerError(
                f"API error {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
                body=resp.text,
            )

        return resp.text

    # ── Market Data ──────────────────────────────────────────────────────

    async def get_quote(self, scrip_code: str, symbol: str = "") -> Quote:
        """Fetch full quote for a single scrip code.

        Endpoint: ``GET /market/quotes/full?scrip-codes=NSE_2885``

        Args:
            scrip_code: Instrument identifier like ``NSE_2885`` from instruments CSV.
            symbol: Optional human-readable name for the returned Quote object.

        Real response::

            {"NSE_2885": {"live_price": 1361.3, "day_change": -32.6,
             "day_change_percentage": -2.34, "day_open": 1375.5,
             "day_high": 1378.6, "day_low": 1358.6, "prev_close": 1393.9,
             "52week_high": 1611.8, "52week_low": 1114.85, ...}}
        """
        data = await self._request(
            "GET", "/market/quotes/full",
            params={"scrip-codes": scrip_code},
        )

        # Response is dict keyed by scrip_code (e.g. "NSE_2885")
        if isinstance(data, dict):
            quote_data = data.get(scrip_code, data)
            if isinstance(quote_data, dict):
                # Parse exchange from scrip_code (e.g. "NSE_2885" → "NSE")
                exchange = scrip_code.split("_")[0] if "_" in scrip_code else "NSE"
                return Quote(
                    symbol=symbol or scrip_code,
                    exchange=exchange,
                    ltp=float(quote_data.get("live_price", 0)),
                    open=float(quote_data.get("day_open", 0)),
                    high=float(quote_data.get("day_high", 0)),
                    low=float(quote_data.get("day_low", 0)),
                    close=float(quote_data.get("prev_close", 0)),
                    volume=int(quote_data.get("volume", 0)),
                    change=float(quote_data.get("day_change", 0)),
                    change_pct=float(quote_data.get("day_change_percentage", 0)),
                    bid=float(quote_data.get("best_bid_price", 0)),
                    ask=float(quote_data.get("best_ask_price", 0)),
                )

        return Quote(symbol=symbol or scrip_code)

    async def get_quotes(
        self, scrip_codes: list[str], symbols: list[str] | None = None,
    ) -> list[Quote]:
        """Fetch full quotes for multiple scrip codes.

        Endpoint: ``GET /market/quotes/full?scrip-codes=NSE_2885,NSE_11536``

        Args:
            scrip_codes: List of scrip codes like ``["NSE_2885", "NSE_11536"]``.
            symbols: Optional human-readable names (same order as scrip_codes).
        """
        joined = ",".join(scrip_codes)
        data = await self._request(
            "GET", "/market/quotes/full",
            params={"scrip-codes": joined},
        )

        quotes: list[Quote] = []
        if isinstance(data, dict):
            for i, sc in enumerate(scrip_codes):
                qd = data.get(sc, {})
                if isinstance(qd, dict):
                    exchange = sc.split("_")[0] if "_" in sc else "NSE"
                    sym = symbols[i] if symbols and i < len(symbols) else sc
                    quotes.append(Quote(
                        symbol=sym,
                        exchange=exchange,
                        ltp=float(qd.get("live_price", 0)),
                        open=float(qd.get("day_open", 0)),
                        high=float(qd.get("day_high", 0)),
                        low=float(qd.get("day_low", 0)),
                        close=float(qd.get("prev_close", 0)),
                        volume=int(qd.get("volume", 0)),
                        change=float(qd.get("day_change", 0)),
                        change_pct=float(qd.get("day_change_percentage", 0)),
                    ))
        return quotes

    async def get_ltp(self, scrip_code: str) -> float:
        """Fetch just the last traded price.

        Endpoint: ``GET /market/quotes/ltp?scrip-codes=NSE_2885``

        Real response: ``{"NSE_2885": {"live_price": 1362}}``
        """
        data = await self._request(
            "GET", "/market/quotes/ltp",
            params={"scrip-codes": scrip_code},
        )

        if isinstance(data, dict):
            ltp_data = data.get(scrip_code, data)
            if isinstance(ltp_data, dict):
                return float(ltp_data.get("live_price", 0))
            if isinstance(ltp_data, (int, float)):
                return float(ltp_data)
        return 0.0

    async def get_historical(
        self,
        scrip_code: str,
        interval: str = "1day",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> list[HistoricalCandle]:
        """Fetch OHLCV candles.

        Endpoint: ``GET /market/historical/{interval}``

        Args:
            scrip_code: Security identifier like ``NSE_2885`` (from instruments CSV).
            interval: Candle interval — ``1day``, ``1week``, ``1month``,
                ``1minute``, ``5minute``, ``15minute``, ``30minute``,
                ``60minute``, ``1second``, etc.
            start_time: Unix epoch **milliseconds** in IST.
            end_time: Unix epoch **milliseconds** in IST.

        Real response (after ``_request`` unwraps ``data``)::

            {"NSE_2885": {"candles": [
                {"ts": 1740960000, "o": 1204, "h": 1206.45,
                 "l": 1156, "c": 1171.25, "v": 17944938},
                ...
            ]}}

        Input timestamps are epoch **milliseconds**.  Response candle ``ts``
        values are epoch **seconds**.
        """
        params: dict[str, str] = {"scrip-codes": scrip_code}
        if start_time is not None:
            params["start_time"] = str(start_time)
        if end_time is not None:
            params["end_time"] = str(end_time)

        data = await self._request(
            "GET", f"/market/historical/{interval}",
            params=params,
        )

        # Data is nested under scrip_code key: {"NSE_2885": {"candles": [...]}}
        candles_raw: list[Any] = []
        if isinstance(data, dict):
            scrip_data = data.get(scrip_code, data)
            if isinstance(scrip_data, dict):
                candles_raw = scrip_data.get("candles") or []
            elif isinstance(scrip_data, list):
                candles_raw = scrip_data
        elif isinstance(data, list):
            candles_raw = data

        candles: list[HistoricalCandle] = []
        for row in candles_raw:
            if isinstance(row, dict):
                # Object candles: {"ts": epoch_sec, "o":, "h":, "l":, "c":, "v":}
                ts = row.get("ts", 0)
                dt = datetime.fromtimestamp(int(ts))
                candles.append(HistoricalCandle(
                    timestamp=dt,
                    open=float(row.get("o", 0)),
                    high=float(row.get("h", 0)),
                    low=float(row.get("l", 0)),
                    close=float(row.get("c", 0)),
                    volume=int(row.get("v", 0)),
                ))
            elif isinstance(row, list) and len(row) >= 6:
                # Fallback for array candles [ts, o, h, l, c, v]
                ts = row[0]
                if isinstance(ts, (int, float)) and ts > 1e12:
                    dt = datetime.fromtimestamp(ts / 1000)
                else:
                    dt = datetime.fromtimestamp(int(ts))
                candles.append(HistoricalCandle(
                    timestamp=dt,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=int(row[5]),
                ))
        return candles

    async def get_instruments(self, source: str = "equity") -> str:
        """Fetch instruments master as CSV text.

        Endpoint: ``GET /market/instruments?source=equity``

        Returns raw CSV with columns:
        SECURITY_ID, TRADING_SYMBOL, CUSTOM_SYMBOL, EXCH, SEGMENT,
        INSTRUMENT_NAME, LOT_UNITS, EXPIRY_DATE, STRIKE_PRICE,
        OPTION_TYPE, TICK_SIZE, SYMBOL_NAME
        """
        return await self._request_text(
            "GET", "/market/instruments",
            params={"source": source},
        )

    # ── Orders ───────────────────────────────────────────────────────────

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """Place a new order.

        Endpoint: ``POST /order``

        Translates Pythonic field names to INDstocks API names:
            side       → txn_type
            quantity   → qty
            price      → limit_price
        """
        payload: dict[str, Any] = {
            "txn_type": order.side.value,           # side → txn_type
            "exchange": order.exchange.value,
            "segment": order.segment.value,
            "product": order.product.value,
            "order_type": order.order_type.value,
            "validity": order.validity.value,
            "security_id": order.security_id,
            "qty": int(order.quantity),               # quantity → qty (int for JSON)
            "is_amo": order.is_amo,
            "algo_id": order.algo_id,
        }
        if order.price is not None:
            payload["limit_price"] = order.price     # price → limit_price
        if order.trigger_price is not None:
            payload["trigger_price"] = order.trigger_price

        data = await self._request("POST", "/order", json_body=payload, is_order=True)
        logger.info(
            "Order placed: %s %s qty=%d security_id=%s",
            order.side, order.symbol, order.quantity, order.security_id,
        )

        if isinstance(data, dict):
            return OrderResponse(
                order_id=str(data.get("order_id", "")),
                status=str(data.get("status", "PENDING")),
                message=str(data.get("message", "")),
            )
        return OrderResponse(order_id="", status="UNKNOWN", message=str(data))

    async def modify_order(self, req: ModifyOrderRequest) -> OrderResponse:
        """Modify a pending order.

        Endpoint: ``POST /order/modify``
        """
        payload: dict[str, Any] = {
            "order_id": req.order_id,
            "segment": req.segment.value,
        }
        if req.quantity is not None:
            payload["qty"] = req.quantity           # quantity → qty
        if req.price is not None:
            payload["limit_price"] = req.price      # price → limit_price

        data = await self._request(
            "POST", "/order/modify", json_body=payload, is_order=True,
        )
        if isinstance(data, dict):
            return OrderResponse(
                order_id=req.order_id,
                status=str(data.get("status", "PENDING")),
                message=str(data.get("message", "")),
            )
        return OrderResponse(order_id=req.order_id, status="UNKNOWN", message=str(data))

    async def cancel_order(self, req: CancelOrderRequest) -> OrderResponse:
        """Cancel a pending order.

        Endpoint: ``POST /order/cancel``
        """
        payload = {
            "order_id": req.order_id,
            "segment": req.segment.value,
        }
        data = await self._request(
            "POST", "/order/cancel", json_body=payload, is_order=True,
        )
        if isinstance(data, dict):
            return OrderResponse(
                order_id=req.order_id,
                status=str(data.get("status", "CANCELLED")),
                message=str(data.get("message", "Cancelled")),
            )
        return OrderResponse(order_id=req.order_id, status="CANCELLED", message=str(data))

    async def get_order_book(self) -> list[dict[str, Any]]:
        """Fetch all orders for the day.

        Endpoint: ``GET /order-book``
        """
        data = await self._request("GET", "/order-book")
        if isinstance(data, list):
            return data
        return []

    async def get_orders(self) -> list[OrderResponse]:
        """Fetch today's orders as OrderResponse models.

        Wraps ``get_order_book()`` to provide the same interface as
        ``KiteConnectClient.get_orders()`` for broker-agnostic usage.
        """
        raw = await self.get_order_book()
        return [
            OrderResponse(
                order_id=str(o.get("order_id", "")),
                status=str(o.get("status", "")),
                message=str(o.get("message", "")),
                exchange_order_id=o.get("exchange_order_id"),
            )
            for o in raw
        ]

    async def get_order(self, order_id: str, segment: str = "EQUITY") -> dict[str, Any]:
        """Fetch a single order by ID.

        Endpoint: ``GET /order?order_id=...&segment=...``
        """
        data = await self._request(
            "GET", "/order",
            params={"order_id": order_id, "segment": segment},
        )
        if isinstance(data, dict):
            return data
        return {}

    async def get_trades(self, order_id: str) -> list[dict[str, Any]]:
        """Fetch trades for an order.

        Endpoint: ``GET /trades/{order_id}``
        """
        data = await self._request("GET", f"/trades/{order_id}")
        if isinstance(data, list):
            return data
        return []

    async def get_trade_book(self, segment: str = "EQUITY") -> list[dict[str, Any]]:
        """Fetch all trades.

        Endpoint: ``GET /trade-book?segment=...``
        """
        data = await self._request(
            "GET", "/trade-book",
            params={"segment": segment},
        )
        if isinstance(data, list):
            return data
        return []

    # ── Portfolio ─────────────────────────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        """Fetch current open positions.

        Endpoint: ``GET /portfolio/positions``
        """
        data = await self._request("GET", "/portfolio/positions")
        if isinstance(data, list):
            return [Position(**p) for p in data]
        return []

    async def get_holdings(self) -> list[Holding]:
        """Fetch delivery holdings.

        Endpoint: ``GET /portfolio/holdings``
        """
        data = await self._request("GET", "/portfolio/holdings")
        if isinstance(data, list):
            return [Holding(**h) for h in data]
        return []

    async def get_funds(self) -> Funds:
        """Fetch available funds and margin.

        Endpoint: ``GET /funds``
        """
        data = await self._request("GET", "/funds")
        if isinstance(data, dict):
            # INDstocks returns nested structure — map to our flat model.
            # Key fields: detailed_avl_balance.eq_cnc (equity CNC buying power),
            # funds_added, sod_balance, pledge_received.
            avl = data.get("detailed_avl_balance", {})
            eq_cnc = float(avl.get("eq_cnc", 0))
            pledge = float(data.get("pledge_received", 0))

            return Funds(
                available_cash=eq_cnc,
                available_margin=eq_cnc,
                used_margin=0.0,
                total_collateral=eq_cnc + pledge,
            )
        return Funds()

    # ── User ─────────────────────────────────────────────────────────────

    async def get_profile(self) -> UserProfile:
        """Fetch authenticated user's profile.

        Endpoint: ``GET /user/profile``
        """
        data = await self._request("GET", "/user/profile")
        if isinstance(data, dict):
            return UserProfile(**data)
        return UserProfile()

    # ── Options ──────────────────────────────────────────────────────────

    async def get_option_chain(self, symbol: str) -> OptionChain:
        """Fetch option chain for a symbol.

        Endpoint: ``GET /option-chain``
        """
        data = await self._request(
            "GET", "/option-chain",
            params={"symbol": symbol},
        )
        if isinstance(data, dict):
            calls = [OptionData(**c) for c in data.get("calls", [])]
            puts = [OptionData(**p) for p in data.get("puts", [])]
            return OptionChain(
                symbol=symbol,
                calls=calls,
                puts=puts,
                spot_price=float(data.get("spot_price", 0)),
                pcr=float(data.get("pcr", 0)),
            )
        return OptionChain(symbol=symbol)

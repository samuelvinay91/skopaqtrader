"""Routes orders to paper engine or live broker based on trading mode.

The router is intentionally thin — it checks ``config.trading_mode`` and
dispatches to the appropriate execution backend.  Switching paper → live
is a config change, not a code change.

Supports multiple brokers (INDstocks, Kite Connect) — the ``live_client``
parameter accepts either client type.
"""

from __future__ import annotations

import logging
from typing import Optional, Protocol, Union

from skopaq.broker.models import (
    ExecutionResult,
    Funds,
    Holding,
    OrderRequest,
    OrderResponse,
    Position,
    TradingSignal,
)
from skopaq.broker.paper_engine import PaperEngine
from skopaq.config import SkopaqConfig

logger = logging.getLogger(__name__)


class BrokerClient(Protocol):
    """Protocol that both INDstocksClient and KiteConnectClient satisfy.

    This allows OrderRouter to accept either broker without tight coupling.
    """

    async def place_order(self, order: OrderRequest) -> OrderResponse: ...
    async def get_positions(self) -> list[Position]: ...
    async def get_holdings(self) -> list[Holding]: ...
    async def get_funds(self) -> Funds: ...


class OrderRouter:
    """Routes orders to the correct execution backend.

    In ``paper`` mode all orders go through the PaperEngine.
    In ``live`` mode orders go to the configured broker (INDstocks or Kite).

    Args:
        config: Application configuration (determines mode).
        paper_engine: Paper trading engine instance.
        live_client: Broker REST client (INDstocks or Kite; can be None in paper-only mode).
    """

    def __init__(
        self,
        config: SkopaqConfig,
        paper_engine: PaperEngine,
        live_client: Optional[Union[BrokerClient]] = None,
    ) -> None:
        self._mode = config.trading_mode
        self._broker = config.broker
        self._paper = paper_engine
        self._live = live_client

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def broker(self) -> str:
        return self._broker

    async def execute(
        self,
        order: OrderRequest,
        signal: Optional[TradingSignal] = None,
    ) -> ExecutionResult:
        """Route an order to the appropriate backend."""
        if self._mode == "live":
            return await self._execute_live(order, signal)
        return await self._execute_paper(order, signal)

    async def _execute_paper(
        self,
        order: OrderRequest,
        signal: Optional[TradingSignal],
    ) -> ExecutionResult:
        """Execute via paper engine.

        Uses async execution (with auto-refresh) when a MarketDataProvider
        is attached, otherwise falls back to synchronous execution.
        """
        if self._paper._market_data is not None:
            return await self._paper.execute_order_async(order, signal)
        return self._paper.execute_order(order, signal)

    async def _execute_live(
        self,
        order: OrderRequest,
        signal: Optional[TradingSignal],
    ) -> ExecutionResult:
        """Execute via live broker API (INDstocks or Kite Connect).

        For INDstocks: resolves ``security_id`` from instruments CSV.
        For Kite: uses ``tradingsymbol`` directly (no extra resolution needed).
        """
        if self._live is None:
            logger.error("Live client not configured — falling back to paper")
            return await self._execute_paper(order, signal)

        try:
            # INDstocks requires security_id resolution before placing
            if self._broker == "indstocks" and not order.security_id:
                from skopaq.broker.scrip_resolver import resolve_security_id

                order.security_id = await resolve_security_id(
                    self._live, order.symbol, order.exchange.value,
                )
                logger.info(
                    "Resolved %s → security_id=%s",
                    order.symbol, order.security_id,
                )

            response = await self._live.place_order(order)

            # Kite brokerage: ₹20 per executed order or 0.03%, whichever is lower
            brokerage = 20.0 if self._broker == "kite" else 20.0

            return ExecutionResult(
                success=True,
                order=response,
                signal=signal,
                mode="live",
                fill_price=order.price,   # Limit price (actual fill via order book)
                brokerage=brokerage,
            )
        except Exception as exc:
            logger.error("Live order failed: %s — NOT falling back to paper", exc)
            return ExecutionResult(
                success=False,
                signal=signal,
                mode="live",
                rejection_reason=f"Broker error: {exc}",
            )

    # ── Portfolio queries (unified interface) ─────────────────────────────

    async def get_positions(self) -> list[Position]:
        """Get positions from the active backend."""
        if self._mode == "live" and self._live:
            return await self._live.get_positions()
        return self._paper.get_positions()

    async def get_holdings(self) -> list[Holding]:
        """Get holdings from the active backend."""
        if self._mode == "live" and self._live:
            return await self._live.get_holdings()
        return self._paper.get_holdings()

    async def get_funds(self) -> Funds:
        """Get funds from the active backend."""
        if self._mode == "live" and self._live:
            return await self._live.get_funds()
        return self._paper.get_funds()

    async def get_orders(self) -> list[OrderResponse]:
        """Get today's orders from the active backend."""
        if self._mode == "live" and self._live:
            # Both brokers expose get_order_book() returning list[dict]
            # but we need OrderResponse. Kite client has get_orders().
            from skopaq.broker.kite_client import KiteConnectClient

            if isinstance(self._live, KiteConnectClient):
                return await self._live.get_orders()

            # INDstocksClient — get_order_book returns raw dicts
            from skopaq.broker.client import INDstocksClient

            if isinstance(self._live, INDstocksClient):
                raw = await self._live.get_order_book()
                return [
                    OrderResponse(
                        order_id=str(o.get("order_id", "")),
                        status=str(o.get("status", "")),
                        message=str(o.get("message", "")),
                    )
                    for o in raw
                ]
        return self._paper.get_orders()

"""Signal-to-execution pipeline.

Orchestrates the full flow: parse signal → build order → safety check →
route to broker → log result.  This is the single entry point for all
trade execution.
"""

from __future__ import annotations

import logging
from typing import Optional

from skopaq.broker.models import (
    ExecutionResult,
    OrderRequest,
    OrderType,
    Product,
    Side,
    TradingSignal,
)
from skopaq.execution.order_router import OrderRouter
from skopaq.execution.safety_checker import SafetyChecker

logger = logging.getLogger(__name__)


class Executor:
    """Orchestrates trade execution from signal to fill.

    Pipeline::

        TradingSignal → OrderRequest → SafetyChecker → OrderRouter → ExecutionResult

    Args:
        router: Routes orders to paper or live backend.
        safety: Validates orders against immutable safety rules.
    """

    def __init__(self, router: OrderRouter, safety: SafetyChecker) -> None:
        self._router = router
        self._safety = safety

    async def execute_signal(self, signal: TradingSignal) -> ExecutionResult:
        """Execute a trading signal through the full pipeline.

        Steps:
            1. Convert signal to an OrderRequest.
            2. Run safety checks against current portfolio.
            3. Route to paper engine or live broker.
            4. Record P&L for loss tracking.
            5. Return ExecutionResult.
        """
        # Step 1: Build order from signal
        order = self._build_order(signal)
        if order is None:
            return ExecutionResult(
                success=False,
                signal=signal,
                mode=self._router.mode,
                safety_passed=False,
                rejection_reason=f"Cannot build order from signal: action={signal.action}",
            )

        # Step 2: Safety checks
        positions = await self._router.get_positions()
        funds = await self._router.get_funds()
        portfolio_value = funds.total_collateral or funds.available_cash

        safety_result = self._safety.validate(
            order=order,
            signal=signal,
            positions=positions,
            funds=funds,
            portfolio_value=portfolio_value,
        )

        if not safety_result.passed:
            return ExecutionResult(
                success=False,
                signal=signal,
                mode=self._router.mode,
                safety_passed=False,
                rejection_reason=safety_result.reason,
            )

        # Step 3: Route to execution backend
        result = await self._router.execute(order, signal)

        # Step 4: Record P&L for loss tracking (on fills)
        if result.success and result.fill_price and signal.action == "SELL":
            # Approximate P&L from signal entry vs fill
            entry = signal.entry_price or 0
            if entry > 0 and order.quantity:
                pnl = (result.fill_price - entry) * order.quantity
                self._safety.record_pnl(pnl)

        logger.info(
            "Execution %s: %s %s qty=%s mode=%s%s",
            "OK" if result.success else "FAILED",
            signal.action,
            signal.symbol,
            signal.quantity or order.quantity,
            result.mode,
            f" reason={result.rejection_reason}" if result.rejection_reason else "",
        )

        return result

    def _build_order(self, signal: TradingSignal) -> Optional[OrderRequest]:
        """Convert a TradingSignal into an OrderRequest."""
        if signal.action == "HOLD":
            return None

        side = Side.BUY if signal.action == "BUY" else Side.SELL

        # Determine order type
        if signal.entry_price:
            order_type = OrderType.LIMIT
        else:
            order_type = OrderType.MARKET

        # Determine quantity
        quantity = signal.quantity or 1  # Default to 1 if not specified

        return OrderRequest(
            symbol=signal.symbol,
            exchange=signal.exchange,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=signal.entry_price,
            trigger_price=signal.stop_loss if side == Side.BUY else None,
            product=Product.CNC,
            tag=f"skopaq-{signal.confidence}",
        )

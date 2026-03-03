"""Signal-to-execution pipeline.

Orchestrates the full flow: parse signal → (optionally) ATR-size →
build order → safety check → route to broker → log result.

This is the single entry point for all trade execution.
"""

from __future__ import annotations

import logging
from datetime import date
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
from skopaq.risk.position_sizer import PositionSizer

logger = logging.getLogger(__name__)


class Executor:
    """Orchestrates trade execution from signal to fill.

    Pipeline::

        TradingSignal → PositionSizer (optional) → OrderRequest
            → SafetyChecker → OrderRouter → ExecutionResult

    Args:
        router: Routes orders to paper or live backend.
        safety: Validates orders against immutable safety rules.
        position_sizer: ATR-based position sizer (None = use signal's quantity).
    """

    def __init__(
        self,
        router: OrderRouter,
        safety: SafetyChecker,
        position_sizer: Optional[PositionSizer] = None,
    ) -> None:
        self._router = router
        self._safety = safety
        self._sizer = position_sizer

    async def execute_signal(
        self,
        signal: TradingSignal,
        trade_date: Optional[str] = None,
        regime_scale: float = 1.0,
        calendar_scale: float = 1.0,
    ) -> ExecutionResult:
        """Execute a trading signal through the full pipeline.

        Steps:
            1. (Optional) Run ATR-based position sizing for BUY signals.
            2. Convert signal to an OrderRequest.
            3. Run safety checks against current portfolio.
            4. Route to paper engine or live broker.
            5. Record P&L for loss tracking.
            6. Return ExecutionResult.

        Args:
            signal: The trading signal to execute.
            trade_date: Current date (YYYY-MM-DD) for ATR lookup.
            regime_scale: Market regime multiplier (0.0–1.2).
            calendar_scale: Event calendar multiplier (0.0–1.0).
        """
        # Step 0: ATR-based position sizing (BUY only)
        if self._sizer and signal.action == "BUY" and signal.entry_price:
            await self._apply_position_sizing(
                signal, trade_date or date.today().isoformat(),
                regime_scale, calendar_scale,
            )

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
                pnl = (result.fill_price - entry) * float(order.quantity)
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

    async def _apply_position_sizing(
        self,
        signal: TradingSignal,
        trade_date: str,
        regime_scale: float,
        calendar_scale: float,
    ) -> None:
        """Compute ATR-based position size and mutate the signal in place.

        Overrides signal.quantity and signal.stop_loss with risk-adjusted values.
        Falls back gracefully if ATR data is unavailable.
        """
        try:
            funds = await self._router.get_funds()
            equity = funds.total_collateral or funds.available_cash

            size = self._sizer.compute_size(
                equity=equity,
                price=signal.entry_price,
                symbol=signal.symbol,
                trade_date=trade_date,
                regime_scale=regime_scale,
                calendar_scale=calendar_scale,
            )

            # Mutate signal with computed values
            signal.quantity = size.quantity
            signal.stop_loss = size.stop_loss

            logger.info(
                "Position sized %s: qty=%d, stop=%.2f, risk=%.0f INR, "
                "ATR=%.2f (%s), regime=%.1f, calendar=%.1f",
                signal.symbol, size.quantity, size.stop_loss, size.risk_amount,
                size.atr, size.atr_source, regime_scale, calendar_scale,
            )

        except Exception:
            logger.warning(
                "Position sizing failed for %s — using signal defaults",
                signal.symbol, exc_info=True,
            )

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

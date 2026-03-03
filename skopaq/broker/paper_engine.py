"""Paper trading engine — simulated execution with real market prices.

Maintains virtual capital, positions, and P&L.  Uses the same interface
as live order execution so switching from paper → live only changes
the execution backend.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from skopaq.broker.models import (
    Exchange,
    ExecutionResult,
    Funds,
    Holding,
    OrderRequest,
    OrderResponse,
    OrderStatus,
    OrderType,
    Position,
    PortfolioSnapshot,
    Quote,
    Side,
    TradingSignal,
)

logger = logging.getLogger(__name__)

# Default simulation parameters
DEFAULT_SLIPPAGE_PCT = 0.001  # 0.1%
DEFAULT_BROKERAGE_INR = 5.0  # INR flat per executed order


class PaperEngine:
    """Simulated execution engine for paper trading.

    Tracks positions, cash, and P&L using real-time quotes.

    Args:
        initial_capital: Starting cash in INR (default 10 lakh).
        slippage_pct: Simulated slippage as a fraction (default 0.1%).
        brokerage: Flat brokerage per order in INR (default 5).
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
        brokerage: float = DEFAULT_BROKERAGE_INR,
        brokerage_pct: float = 0.0,
        currency_label: str = "INR",
    ) -> None:
        self._initial_capital = Decimal(str(initial_capital))
        self._cash = Decimal(str(initial_capital))
        self._slippage_pct = slippage_pct
        self._brokerage = Decimal(str(brokerage))
        self._brokerage_pct = Decimal(str(brokerage_pct))
        self._currency_label = currency_label

        # {symbol: Position}
        self._positions: dict[str, Position] = {}

        # Completed order history
        self._orders: list[OrderResponse] = []

        # Latest quotes cache — updated by websocket or manual refresh
        self._quotes: dict[str, Quote] = {}

        # Daily P&L tracking
        self._day_pnl = Decimal("0")
        self._trade_count = 0

    # ── Quote management ─────────────────────────────────────────────────

    def update_quote(self, quote: Quote) -> None:
        """Update cached quote for a symbol (called by websocket handler)."""
        self._quotes[quote.symbol] = quote

    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Get the last known quote for a symbol."""
        return self._quotes.get(symbol)

    # ── Order execution ──────────────────────────────────────────────────

    def execute_order(
        self,
        order: OrderRequest,
        signal: Optional[TradingSignal] = None,
    ) -> ExecutionResult:
        """Simulate order execution against cached quotes.

        Returns an ``ExecutionResult`` indicating success/failure, fill price,
        slippage, and brokerage.
        """
        quote = self._quotes.get(order.symbol)
        if quote is None:
            return ExecutionResult(
                success=False,
                mode="paper",
                rejection_reason=f"No quote available for {order.symbol}",
                signal=signal,
            )

        # Determine base fill price
        base_price = self._determine_fill_price(order, quote)
        if base_price is None:
            return ExecutionResult(
                success=False,
                mode="paper",
                rejection_reason=f"Cannot fill {order.order_type} order — conditions not met",
                signal=signal,
            )

        # Apply slippage
        slippage_direction = 1 if order.side == Side.BUY else -1
        slippage_amount = base_price * self._slippage_pct * slippage_direction
        # Add small random jitter (±20% of slippage)
        jitter = slippage_amount * random.uniform(-0.2, 0.2)
        fill_price = round(base_price + slippage_amount + jitter, 2)
        fill_price = max(fill_price, 0.01)  # Never negative

        # Calculate order value
        order_value = Decimal(str(fill_price)) * order.quantity

        # Compute brokerage: percentage-based (crypto) or flat (equity)
        if self._brokerage_pct > 0:
            trade_brokerage = order_value * self._brokerage_pct
        else:
            trade_brokerage = self._brokerage

        # Check sufficient cash for buys
        if order.side == Side.BUY:
            total_cost = order_value + trade_brokerage
            if total_cost > self._cash:
                return ExecutionResult(
                    success=False,
                    mode="paper",
                    rejection_reason=(
                        f"Insufficient funds: need {total_cost} {self._currency_label}, "
                        f"have {self._cash} {self._currency_label}"
                    ),
                    signal=signal,
                )

        # Execute the fill
        self._apply_fill(order, fill_price, trade_brokerage)

        # Record the order
        order_resp = OrderResponse(
            order_id=f"PAPER-{uuid4().hex[:12].upper()}",
            status=OrderStatus.COMPLETE,
            message=f"Paper fill at {fill_price}",
            timestamp=datetime.now(timezone.utc),
        )
        self._orders.append(order_resp)
        self._trade_count += 1

        actual_slippage = round(fill_price - base_price, 2)
        logger.info(
            "Paper %s %s x%s @ %.2f (slippage=%.2f, brokerage=%.4f %s)",
            order.side, order.symbol, order.quantity, fill_price,
            actual_slippage, float(trade_brokerage), self._currency_label,
        )

        return ExecutionResult(
            success=True,
            order=order_resp,
            signal=signal,
            mode="paper",
            fill_price=fill_price,
            slippage=actual_slippage,
            brokerage=float(trade_brokerage),
            timestamp=datetime.now(timezone.utc),
        )

    def _determine_fill_price(self, order: OrderRequest, quote: Quote) -> Optional[float]:
        """Determine the base fill price based on order type and market data."""
        if order.order_type == OrderType.MARKET:
            # Market order fills at bid (sell) or ask (buy)
            if order.side == Side.BUY:
                return quote.ask if quote.ask > 0 else quote.ltp
            return quote.bid if quote.bid > 0 else quote.ltp

        if order.order_type == OrderType.LIMIT:
            if order.price is None:
                return None
            # Limit order fills only if price is favourable
            if order.side == Side.BUY and quote.ltp <= order.price:
                return quote.ltp
            if order.side == Side.SELL and quote.ltp >= order.price:
                return quote.ltp
            return None  # Limit not yet triggered

        if order.order_type in (OrderType.SL, OrderType.SLM):
            if order.trigger_price is None:
                return None
            # SL triggers when price crosses trigger level
            if order.side == Side.BUY and quote.ltp >= order.trigger_price:
                return order.price if order.price else quote.ltp
            if order.side == Side.SELL and quote.ltp <= order.trigger_price:
                return order.price if order.price else quote.ltp
            return None  # SL not yet triggered

        return None

    def _apply_fill(self, order: OrderRequest, fill_price: float, brokerage: Decimal | None = None) -> None:
        """Update positions and cash after a fill."""
        symbol = order.symbol
        qty = order.quantity
        price_d = Decimal(str(fill_price))  # Decimal-safe price for all arithmetic
        value = price_d * qty
        fee = brokerage if brokerage is not None else self._brokerage

        if order.side == Side.BUY:
            self._cash -= value + fee
            existing = self._positions.get(symbol)
            if existing and existing.quantity > 0:
                # Average up the position
                total_qty = existing.quantity + qty
                avg_price = (
                    (Decimal(str(existing.average_price)) * existing.quantity + price_d * qty)
                    / total_qty
                )
                self._positions[symbol] = Position(
                    symbol=symbol,
                    exchange=order.exchange,
                    product=order.product,
                    quantity=total_qty,
                    average_price=float(round(avg_price, 2)),
                    last_price=fill_price,
                    pnl=0.0,
                    day_pnl=0.0,
                    buy_quantity=existing.buy_quantity + qty,
                    sell_quantity=existing.sell_quantity,
                    buy_value=existing.buy_value + float(value),
                    sell_value=existing.sell_value,
                )
            else:
                self._positions[symbol] = Position(
                    symbol=symbol,
                    exchange=order.exchange,
                    product=order.product,
                    quantity=qty,
                    average_price=fill_price,
                    last_price=fill_price,
                    pnl=0.0,
                    day_pnl=0.0,
                    buy_quantity=qty,
                    sell_quantity=Decimal("0"),
                    buy_value=float(value),
                    sell_value=0.0,
                )
        else:
            # SELL
            self._cash += value - fee
            existing = self._positions.get(symbol)
            if existing:
                remaining = existing.quantity - qty
                pnl = float(price_d - Decimal(str(existing.average_price))) * float(qty)
                self._day_pnl += Decimal(str(pnl))

                if remaining <= 0:
                    # Position fully closed
                    del self._positions[symbol]
                else:
                    self._positions[symbol] = Position(
                        symbol=symbol,
                        exchange=existing.exchange,
                        product=existing.product,
                        quantity=remaining,
                        average_price=existing.average_price,
                        last_price=fill_price,
                        pnl=existing.pnl + pnl,
                        day_pnl=existing.day_pnl + pnl,
                        buy_quantity=existing.buy_quantity,
                        sell_quantity=existing.sell_quantity + qty,
                        buy_value=existing.buy_value,
                        sell_value=existing.sell_value + float(value),
                    )

    # ── Portfolio queries ────────────────────────────────────────────────

    def get_positions(self) -> list[Position]:
        """Return all open positions with updated P&L from latest quotes."""
        result = []
        for symbol, pos in self._positions.items():
            quote = self._quotes.get(symbol)
            if quote:
                pnl = (quote.ltp - pos.average_price) * float(pos.quantity)
                pos = pos.model_copy(update={"last_price": quote.ltp, "pnl": round(pnl, 2)})
            result.append(pos)
        return result

    def get_holdings(self) -> list[Holding]:
        """Return positions formatted as holdings (for CNC delivery positions)."""
        return [
            Holding(
                symbol=p.symbol,
                exchange=p.exchange,
                quantity=p.quantity,
                average_price=p.average_price,
                last_price=p.last_price,
                pnl=p.pnl,
            )
            for p in self.get_positions()
        ]

    def get_funds(self) -> Funds:
        """Return current cash and margin status."""
        positions_value = sum(
            Decimal(str(p.last_price)) * p.quantity for p in self._positions.values()
        )
        return Funds(
            available_cash=float(self._cash),
            used_margin=float(positions_value),
            available_margin=float(self._cash),
            total_collateral=float(self._cash + positions_value),
        )

    def get_snapshot(self) -> PortfolioSnapshot:
        """Return a complete portfolio snapshot."""
        funds = self.get_funds()
        positions = self.get_positions()
        positions_value = sum(
            Decimal(str(p.last_price)) * p.quantity for p in positions
        )
        return PortfolioSnapshot(
            timestamp=datetime.now(timezone.utc),
            total_value=self._cash + positions_value,
            cash=self._cash,
            positions_value=positions_value,
            day_pnl=self._day_pnl,
            positions=positions,
            open_orders=0,
        )

    def get_orders(self) -> list[OrderResponse]:
        """Return all paper orders placed today."""
        return list(self._orders)

    # ── Day reset ────────────────────────────────────────────────────────

    def reset_day(self) -> None:
        """Reset daily counters (call at start of trading day)."""
        self._day_pnl = Decimal("0")
        self._trade_count = 0
        self._orders.clear()
        logger.info("Paper engine day reset. Cash: %s", self._cash)

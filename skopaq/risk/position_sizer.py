"""ATR-based position sizing.

Computes risk-adjusted position size using Average True Range (ATR)
volatility.  A high-ATR stock gets a smaller position; a low-ATR stock
gets a larger position — so every trade risks roughly the same amount
of capital regardless of the underlying's volatility.

Formula::

    risk_amount  = equity * risk_per_trade_pct       # e.g., 1% of 10L = 10,000
    stop_distance = atr * atr_multiplier             # e.g., 45 * 2.0 = 90 INR
    quantity     = floor(risk_amount / stop_distance) # e.g., 10000 / 90 = 111 shares
    stop_loss    = entry_price - stop_distance        # BUY stop below entry

This is the same formula used by turtle traders, Van Tharp's "R-multiples",
and most institutional risk desks.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

from skopaq.risk.atr import estimate_atr, fetch_atr

logger = logging.getLogger(__name__)


@dataclass
class PositionSize:
    """Result of a position sizing computation."""

    quantity: int
    stop_loss: float
    risk_amount: float
    atr: float
    atr_source: str  # "vendor" or "estimate"


class PositionSizer:
    """Computes volatility-adjusted position sizes using ATR.

    Args:
        risk_per_trade_pct: Fraction of equity to risk per trade (default 1%).
        atr_multiplier: Stop distance in ATR units (default 2.0).
        atr_period: ATR lookback period in days (default 14).
        min_quantity: Minimum shares to buy (default 1).
    """

    def __init__(
        self,
        risk_per_trade_pct: float = 0.01,
        atr_multiplier: float = 2.0,
        atr_period: int = 14,
        min_quantity: int = 1,
    ) -> None:
        self._risk_pct = risk_per_trade_pct
        self._atr_mult = atr_multiplier
        self._atr_period = atr_period
        self._min_qty = min_quantity

    def compute_size(
        self,
        equity: float,
        price: float,
        symbol: str,
        trade_date: str,
        regime_scale: float = 1.0,
        calendar_scale: float = 1.0,
    ) -> PositionSize:
        """Compute position size for a trade.

        Args:
            equity: Current portfolio equity (INR).
            price: Entry price for the stock.
            symbol: Stock symbol (e.g., "RELIANCE").
            trade_date: Current date (YYYY-MM-DD) for ATR lookup.
            regime_scale: Market regime multiplier (0.0–1.2, default 1.0).
            calendar_scale: Event calendar multiplier (0.0–1.0, default 1.0).

        Returns:
            PositionSize with quantity, stop_loss, risk_amount, and ATR value.
        """
        if equity <= 0 or price <= 0:
            logger.warning("Invalid equity=%s or price=%s — returning minimum", equity, price)
            return PositionSize(
                quantity=self._min_qty,
                stop_loss=price * 0.98,  # Default 2% stop
                risk_amount=0,
                atr=estimate_atr(price),
                atr_source="estimate",
            )

        # Fetch ATR from vendor; fall back to estimate
        atr = fetch_atr(symbol, trade_date, self._atr_period)
        atr_source = "vendor"

        if atr is None or atr <= 0:
            atr = estimate_atr(price)
            atr_source = "estimate"

        # Compute risk budget
        risk_amount = equity * self._risk_pct

        # Apply regime + calendar scaling to risk budget
        effective_scale = max(0.0, min(regime_scale * calendar_scale, 1.5))
        risk_amount *= effective_scale

        # Stop distance in price units
        stop_distance = atr * self._atr_mult

        # Prevent division by zero or absurdly tight stops
        if stop_distance < price * 0.005:  # At least 0.5% stop distance
            stop_distance = price * 0.005
            logger.info("ATR stop distance clamped to minimum 0.5%% for %s", symbol)

        # Compute quantity
        raw_quantity = risk_amount / stop_distance
        quantity = max(self._min_qty, math.floor(raw_quantity))

        # Compute stop-loss price (below entry for BUY)
        stop_loss = round(price - stop_distance, 2)

        logger.info(
            "Position sized: %s ATR=%.2f (%s), qty=%d, stop=%.2f, "
            "risk=%.0f INR, scale=%.2f",
            symbol, atr, atr_source, quantity, stop_loss,
            risk_amount, effective_scale,
        )

        return PositionSize(
            quantity=quantity,
            stop_loss=stop_loss,
            risk_amount=risk_amount,
            atr=atr,
            atr_source=atr_source,
        )

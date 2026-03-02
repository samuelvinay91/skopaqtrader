"""Sector concentration checker for portfolio risk management.

Prevents the portfolio from becoming over-exposed to a single sector.
Uses a static NIFTY 50 sector map — simple, reliable, and sufficient
for the current watchlist scope.  Can evolve to a dynamic API lookup later.
"""

from __future__ import annotations

import logging
from typing import Optional

from skopaq.broker.models import Position

logger = logging.getLogger(__name__)


# ── NIFTY 50 Sector Map ──────────────────────────────────────────────────────
# Updated periodically.  Symbols not in this map are classified as "OTHER".

SECTOR_MAP: dict[str, str] = {
    # Oil & Gas / Energy
    "RELIANCE": "OIL_GAS",
    "ONGC": "OIL_GAS",
    "BPCL": "OIL_GAS",
    "NTPC": "ENERGY",
    "POWERGRID": "ENERGY",
    "ADANIENT": "ENERGY",
    "ADANIGREEN": "ENERGY",
    "ADANIPORTS": "INFRASTRUCTURE",
    # Banking
    "HDFCBANK": "BANKING",
    "ICICIBANK": "BANKING",
    "KOTAKBANK": "BANKING",
    "SBIN": "BANKING",
    "AXISBANK": "BANKING",
    "INDUSINDBK": "BANKING",
    "BAJFINANCE": "NBFC",
    "BAJAJFINSV": "NBFC",
    # IT
    "TCS": "IT",
    "INFY": "IT",
    "WIPRO": "IT",
    "HCLTECH": "IT",
    "TECHM": "IT",
    "LTI": "IT",
    # Pharma / Healthcare
    "SUNPHARMA": "PHARMA",
    "DRREDDY": "PHARMA",
    "CIPLA": "PHARMA",
    "DIVISLAB": "PHARMA",
    "APOLLOHOSP": "HEALTHCARE",
    # Auto
    "MARUTI": "AUTO",
    "TATAMOTORS": "AUTO",
    "M&M": "AUTO",
    "BAJAJ-AUTO": "AUTO",
    "HEROMOTOCO": "AUTO",
    "EICHERMOT": "AUTO",
    # FMCG / Consumer
    "HINDUNILVR": "FMCG",
    "ITC": "FMCG",
    "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG",
    "TATACONSUM": "FMCG",
    # Metals & Mining
    "TATASTEEL": "METALS",
    "JSWSTEEL": "METALS",
    "HINDALCO": "METALS",
    "COALINDIA": "METALS",
    # Telecom
    "BHARTIARTL": "TELECOM",
    # Cement / Construction
    "ULTRACEMCO": "CEMENT",
    "GRASIM": "CEMENT",
    "SHREECEM": "CEMENT",
    # Insurance
    "SBILIFE": "INSURANCE",
    "HDFCLIFE": "INSURANCE",
    # Others
    "TITAN": "CONSUMER_DURABLES",
    "ASIANPAINT": "CONSUMER_DURABLES",
    "LTIM": "IT",
    "WIPRO": "IT",
}


def get_sector(symbol: str) -> str:
    """Return the sector for a symbol, or 'OTHER' if unmapped."""
    return SECTOR_MAP.get(symbol.upper(), "OTHER")


class ConcentrationChecker:
    """Checks that a new position won't breach sector concentration limits.

    Args:
        max_sector_pct: Maximum fraction of portfolio value in any one sector.
    """

    def __init__(self, max_sector_pct: float = 0.40) -> None:
        self._max_pct = max_sector_pct

    def check(
        self,
        symbol: str,
        order_value: float,
        positions: list[Position],
        portfolio_value: float,
    ) -> Optional[str]:
        """Check whether adding this order would breach sector limits.

        Args:
            symbol: Symbol being bought.
            order_value: Value of the proposed order (price * quantity).
            positions: Current open positions.
            portfolio_value: Total portfolio value.

        Returns:
            Rejection reason string if limit breached, or None if OK.
        """
        if portfolio_value <= 0:
            return None

        target_sector = get_sector(symbol)
        if target_sector == "OTHER":
            # Unknown sector — cannot check concentration, allow through
            return None

        # Sum existing exposure in the target sector
        sector_exposure = 0.0
        for pos in positions:
            if pos.quantity > 0 and get_sector(pos.symbol) == target_sector:
                sector_exposure += pos.last_price * pos.quantity

        # Add proposed order value
        new_exposure = sector_exposure + order_value
        concentration = new_exposure / portfolio_value

        if concentration > self._max_pct:
            return (
                f"Sector {target_sector} concentration {concentration:.0%} "
                f"would exceed {self._max_pct:.0%} limit "
                f"(existing={sector_exposure:,.0f} + new={order_value:,.0f})"
            )

        return None

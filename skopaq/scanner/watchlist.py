"""Watchlist management for the scanner.

Provides a default NIFTY 50 watchlist plus support for custom lists.
"""

from __future__ import annotations


# NIFTY 50 constituents (as of 2024 — updated periodically)
NIFTY_50: list[str] = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BPCL",
    "BHARTIARTL", "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB",
    "DRREDDY", "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH",
    "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR",
    "ICICIBANK", "ITC", "INDUSINDBK", "INFY", "JSWSTEEL",
    "KOTAKBANK", "LT", "M&M", "MARUTI", "NTPC",
    "NESTLEIND", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE",
    "SBIN", "SUNPHARMA", "TCS", "TATACONSUM", "TATAMOTORS",
    "TATASTEEL", "TECHM", "TITAN", "TRENT", "ULTRACEMCO",
    "WIPRO",
]


class Watchlist:
    """Manages a list of symbols to scan.

    Args:
        symbols: Custom list.  If *None*, defaults to NIFTY 50.
    """

    def __init__(self, symbols: list[str] | None = None) -> None:
        self._symbols: list[str] = list(symbols) if symbols else list(NIFTY_50)

    @property
    def symbols(self) -> list[str]:
        return list(self._symbols)

    def __len__(self) -> int:
        return len(self._symbols)

    def __contains__(self, symbol: str) -> bool:
        return symbol.upper() in (s.upper() for s in self._symbols)

    def add(self, symbol: str) -> None:
        """Add a symbol if not already present."""
        upper = symbol.upper()
        if upper not in (s.upper() for s in self._symbols):
            self._symbols.append(upper)

    def remove(self, symbol: str) -> None:
        """Remove a symbol (case-insensitive)."""
        upper = symbol.upper()
        self._symbols = [s for s in self._symbols if s.upper() != upper]

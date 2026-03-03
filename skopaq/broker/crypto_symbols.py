"""Crypto symbol mapping and top-coin watchlist.

Maps between three symbol formats used across the system:

    Binance pair:    ``BTCUSDT``   (for quotes and paper execution)
    yfinance ticker: ``BTC-USD``   (for upstream agent analysis)
    Base coin:       ``BTC``       (human-friendly display)

The CRYPTO_TOP_20 list provides a scanner watchlist comparable to NIFTY_50
for equities.
"""

from __future__ import annotations

# ── Known quote currencies (ordered by priority for stripping) ─────────────
_QUOTE_CURRENCIES = ("USDT", "BUSD", "USDC", "USD")


def to_binance_pair(symbol: str, quote: str = "USDT") -> str:
    """Ensure a symbol is in Binance pair format (e.g., ``BTCUSDT``).

    Args:
        symbol: Any format — ``BTC``, ``BTCUSDT``, ``BTC-USD``, ``btcusdt``.
        quote: Quote currency to append if not already present.

    Returns:
        Uppercase Binance pair like ``BTCUSDT``.

    Examples::

        >>> to_binance_pair("BTC")
        'BTCUSDT'
        >>> to_binance_pair("BTCUSDT")
        'BTCUSDT'
        >>> to_binance_pair("BTC-USD")
        'BTCUSDT'
    """
    s = symbol.upper().strip()

    # Handle yfinance format: BTC-USD → BTC
    if "-" in s:
        s = s.split("-")[0]

    # If already ends with a known quote currency, return as-is
    for qc in _QUOTE_CURRENCIES:
        if s.endswith(qc):
            return s

    return s + quote.upper()


def to_yfinance_ticker(symbol: str, quote: str = "USD") -> str:
    """Convert to yfinance crypto format (e.g., ``BTC-USD``).

    Args:
        symbol: Any format — ``BTCUSDT``, ``BTC``, ``BTC-USD``.
        quote: Quote currency for yfinance (always USD for crypto).

    Returns:
        yfinance ticker like ``BTC-USD``.

    Examples::

        >>> to_yfinance_ticker("BTCUSDT")
        'BTC-USD'
        >>> to_yfinance_ticker("BTC")
        'BTC-USD'
        >>> to_yfinance_ticker("BTC-USD")
        'BTC-USD'
    """
    s = symbol.upper().strip()

    # Already in yfinance format
    if "-" in s:
        return s

    # Strip known quote currencies
    base = _strip_quote(s)
    return f"{base}-{quote.upper()}"


def from_binance_pair(pair: str) -> tuple[str, str]:
    """Split a Binance pair into base and quote currencies.

    Args:
        pair: Binance pair like ``BTCUSDT``.

    Returns:
        Tuple of ``(base, quote)`` like ``("BTC", "USDT")``.

    Examples::

        >>> from_binance_pair("BTCUSDT")
        ('BTC', 'USDT')
        >>> from_binance_pair("ETHBUSD")
        ('ETH', 'BUSD')
    """
    s = pair.upper().strip()
    for qc in _QUOTE_CURRENCIES:
        if s.endswith(qc):
            base = s[: -len(qc)]
            if base:  # Guard against empty base
                return base, qc
    # Fallback: assume last 4 chars are quote (USDT)
    return s[:-4], s[-4:]


def _strip_quote(s: str) -> str:
    """Strip known quote currency suffix from a symbol."""
    for qc in _QUOTE_CURRENCIES:
        if s.endswith(qc) and len(s) > len(qc):
            return s[: -len(qc)]
    return s


# ── Top 20 Crypto Coins by Market Cap ─────────────────────────────────────
# Used as the default crypto watchlist for the scanner.
# All pairs use USDT as quote currency (Binance's most liquid market).

CRYPTO_TOP_20: list[str] = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "DOTUSDT",
    "LINKUSDT",
    "MATICUSDT",
    "UNIUSDT",
    "ATOMUSDT",
    "LTCUSDT",
    "NEARUSDT",
    "AAVEUSDT",
    "FILUSDT",
    "ARBUSDT",
    "OPUSDT",
    "APTUSDT",
]

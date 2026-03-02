"""Market regime detection using India VIX + NIFTY trend filter.

Classifies the current market into one of four regimes and returns a
position-scaling multiplier.  In high-volatility or crisis regimes the
system automatically reduces position size — or halts trading entirely.

Regime grid::

    VIX < 13       → LOW_VOL    (complacent market, trend-following friendly)
    13 ≤ VIX < 20  → NORMAL     (typical volatility)
    20 ≤ VIX < 30  → HIGH_VOL   (elevated fear, reduce size)
    VIX ≥ 30       → CRISIS     (panic, go to cash)

Trend overlay::

    NIFTY > 200 SMA  → UPTREND
    NIFTY ≤ 200 SMA  → DOWNTREND

Position scale::

    LOW_VOL  + UPTREND   = 1.2  (full gas)
    NORMAL   + UPTREND   = 1.0  (standard)
    NORMAL   + DOWNTREND = 0.7  (cautious)
    HIGH_VOL + any       = 0.5  (half size)
    CRISIS   + any       = 0.0  (no new trades)

Data sources:
    - India VIX: ``^INDIAVIX`` via yfinance
    - NIFTY 50: ``^NSEI`` via yfinance (for SMA calculation)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ── VIX thresholds (empirical, Indian market specific) ──────────────────────

VIX_LOW_THRESHOLD = 13.0
VIX_NORMAL_THRESHOLD = 20.0
VIX_HIGH_THRESHOLD = 30.0


# ── Position scale matrix ───────────────────────────────────────────────────
# Key: (vix_regime, trend) → scale
_SCALE_MATRIX: dict[tuple[str, str], float] = {
    ("LOW_VOL", "UPTREND"): 1.2,
    ("LOW_VOL", "DOWNTREND"): 0.8,
    ("LOW_VOL", "SIDEWAYS"): 1.0,
    ("NORMAL", "UPTREND"): 1.0,
    ("NORMAL", "DOWNTREND"): 0.7,
    ("NORMAL", "SIDEWAYS"): 0.8,
    ("HIGH_VOL", "UPTREND"): 0.5,
    ("HIGH_VOL", "DOWNTREND"): 0.3,
    ("HIGH_VOL", "SIDEWAYS"): 0.4,
    ("CRISIS", "UPTREND"): 0.0,
    ("CRISIS", "DOWNTREND"): 0.0,
    ("CRISIS", "SIDEWAYS"): 0.0,
}


@dataclass
class MarketRegime:
    """Classification of the current market state."""

    label: str  # "LOW_VOL", "NORMAL", "HIGH_VOL", "CRISIS"
    vix: Optional[float]  # India VIX value, or None if unavailable
    trend: str  # "UPTREND", "DOWNTREND", "SIDEWAYS"
    position_scale: float  # Multiplier for position sizing (0.0 – 1.2)

    @property
    def should_trade(self) -> bool:
        """Whether the system should accept new trades."""
        return self.position_scale > 0.0


class RegimeDetector:
    """Classifies the current market regime from India VIX and NIFTY trend.

    This is a stateless classifier — give it data and it returns a regime.
    Data fetching is the caller's responsibility (keeps this class testable).
    """

    def detect(
        self,
        india_vix: Optional[float] = None,
        nifty_price: Optional[float] = None,
        nifty_sma200: Optional[float] = None,
    ) -> MarketRegime:
        """Classify current market regime.

        Args:
            india_vix: Current India VIX level (None = assume NORMAL).
            nifty_price: Current NIFTY 50 spot price.
            nifty_sma200: NIFTY 50 200-day simple moving average.

        Returns:
            MarketRegime with label, VIX, trend, and position_scale.
        """
        # Step 1: Classify VIX regime
        vix_regime = self._classify_vix(india_vix)

        # Step 2: Classify trend
        trend = self._classify_trend(nifty_price, nifty_sma200)

        # Step 3: Look up position scale
        scale = _SCALE_MATRIX.get((vix_regime, trend), 1.0)

        regime = MarketRegime(
            label=vix_regime,
            vix=india_vix,
            trend=trend,
            position_scale=scale,
        )

        logger.info(
            "Market regime: %s + %s → scale=%.1f (VIX=%.1f)",
            vix_regime, trend, scale,
            india_vix if india_vix is not None else -1,
        )

        return regime

    def _classify_vix(self, india_vix: Optional[float]) -> str:
        """Map India VIX to volatility regime."""
        if india_vix is None:
            return "NORMAL"  # Conservative default when data unavailable

        if india_vix < VIX_LOW_THRESHOLD:
            return "LOW_VOL"
        elif india_vix < VIX_NORMAL_THRESHOLD:
            return "NORMAL"
        elif india_vix < VIX_HIGH_THRESHOLD:
            return "HIGH_VOL"
        else:
            return "CRISIS"

    def _classify_trend(
        self,
        nifty_price: Optional[float],
        nifty_sma200: Optional[float],
    ) -> str:
        """Classify NIFTY trend relative to 200 SMA."""
        if nifty_price is None or nifty_sma200 is None or nifty_sma200 <= 0:
            return "SIDEWAYS"  # Insufficient data

        ratio = nifty_price / nifty_sma200

        if ratio > 1.02:
            return "UPTREND"  # 2% above SMA → clear uptrend
        elif ratio < 0.98:
            return "DOWNTREND"  # 2% below SMA → clear downtrend
        else:
            return "SIDEWAYS"  # Within ±2% band


def fetch_regime_data() -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Fetch India VIX, NIFTY price, and NIFTY 200 SMA from yfinance.

    Returns:
        (india_vix, nifty_price, nifty_sma200) — any may be None on failure.
    """
    try:
        import yfinance as yf

        # India VIX
        india_vix = None
        try:
            vix_ticker = yf.Ticker("^INDIAVIX")
            vix_hist = vix_ticker.history(period="5d")
            if not vix_hist.empty:
                india_vix = float(vix_hist["Close"].iloc[-1])
        except Exception:
            logger.warning("Failed to fetch India VIX", exc_info=True)

        # NIFTY 50 price + SMA200
        nifty_price = None
        nifty_sma200 = None
        try:
            nifty_ticker = yf.Ticker("^NSEI")
            nifty_hist = nifty_ticker.history(period="1y")
            if not nifty_hist.empty:
                nifty_price = float(nifty_hist["Close"].iloc[-1])
                if len(nifty_hist) >= 200:
                    nifty_sma200 = float(nifty_hist["Close"].tail(200).mean())
                else:
                    # Use available data for partial SMA
                    nifty_sma200 = float(nifty_hist["Close"].mean())
                    logger.info(
                        "Using %d-day SMA (< 200 available)", len(nifty_hist)
                    )
        except Exception:
            logger.warning("Failed to fetch NIFTY data", exc_info=True)

        return india_vix, nifty_price, nifty_sma200

    except ImportError:
        logger.warning("yfinance not installed — regime detection unavailable")
        return None, None, None

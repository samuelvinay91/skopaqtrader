"""Tests for market regime detection.

Validates VIX threshold classification, NIFTY trend detection,
and position scale matrix lookup.
"""

import pytest

from skopaq.risk.regime import (
    MarketRegime,
    RegimeDetector,
    VIX_HIGH_THRESHOLD,
    VIX_LOW_THRESHOLD,
    VIX_NORMAL_THRESHOLD,
    _SCALE_MATRIX,
)


@pytest.fixture
def detector():
    return RegimeDetector()


# ── VIX regime classification ─────────────────────────────────────────────────


class TestVIXClassification:
    """Test the four VIX regime buckets."""

    def test_low_vol(self, detector):
        regime = detector.detect(india_vix=10.0, nifty_price=22000, nifty_sma200=21000)
        assert regime.label == "LOW_VOL"

    def test_low_vol_boundary(self, detector):
        """VIX exactly at 13 should be NORMAL, not LOW_VOL."""
        regime = detector.detect(india_vix=13.0, nifty_price=22000, nifty_sma200=21000)
        assert regime.label == "NORMAL"

    def test_normal(self, detector):
        regime = detector.detect(india_vix=15.0, nifty_price=22000, nifty_sma200=21000)
        assert regime.label == "NORMAL"

    def test_high_vol(self, detector):
        regime = detector.detect(india_vix=25.0, nifty_price=22000, nifty_sma200=21000)
        assert regime.label == "HIGH_VOL"

    def test_high_vol_boundary(self, detector):
        """VIX exactly at 20 should be HIGH_VOL."""
        regime = detector.detect(india_vix=20.0, nifty_price=22000, nifty_sma200=21000)
        assert regime.label == "HIGH_VOL"

    def test_crisis(self, detector):
        regime = detector.detect(india_vix=35.0, nifty_price=22000, nifty_sma200=21000)
        assert regime.label == "CRISIS"

    def test_crisis_boundary(self, detector):
        """VIX exactly at 30 should be CRISIS."""
        regime = detector.detect(india_vix=30.0, nifty_price=22000, nifty_sma200=21000)
        assert regime.label == "CRISIS"

    def test_none_vix_defaults_to_normal(self, detector):
        """Missing VIX data → conservative NORMAL assumption."""
        regime = detector.detect(india_vix=None, nifty_price=22000, nifty_sma200=21000)
        assert regime.label == "NORMAL"


# ── Trend classification ──────────────────────────────────────────────────────


class TestTrendClassification:
    """Test NIFTY trend relative to 200 SMA."""

    def test_uptrend(self, detector):
        """Price 5% above SMA → UPTREND."""
        regime = detector.detect(india_vix=15.0, nifty_price=22000, nifty_sma200=21000)
        assert regime.trend == "UPTREND"

    def test_downtrend(self, detector):
        """Price 5% below SMA → DOWNTREND."""
        regime = detector.detect(india_vix=15.0, nifty_price=19000, nifty_sma200=20000)
        assert regime.trend == "DOWNTREND"

    def test_sideways_above(self, detector):
        """Price 1% above SMA → SIDEWAYS (within ±2% band)."""
        regime = detector.detect(india_vix=15.0, nifty_price=20200, nifty_sma200=20000)
        assert regime.trend == "SIDEWAYS"

    def test_sideways_below(self, detector):
        """Price 1% below SMA → SIDEWAYS."""
        regime = detector.detect(india_vix=15.0, nifty_price=19800, nifty_sma200=20000)
        assert regime.trend == "SIDEWAYS"

    def test_exactly_at_2pct_above(self, detector):
        """Price exactly 2% above SMA → SIDEWAYS (boundary: ratio=1.02, need >1.02)."""
        regime = detector.detect(india_vix=15.0, nifty_price=20400, nifty_sma200=20000)
        assert regime.trend == "SIDEWAYS"

    def test_none_price_is_sideways(self, detector):
        """Missing price data → SIDEWAYS."""
        regime = detector.detect(india_vix=15.0, nifty_price=None, nifty_sma200=20000)
        assert regime.trend == "SIDEWAYS"

    def test_none_sma_is_sideways(self, detector):
        """Missing SMA data → SIDEWAYS."""
        regime = detector.detect(india_vix=15.0, nifty_price=22000, nifty_sma200=None)
        assert regime.trend == "SIDEWAYS"

    def test_zero_sma_is_sideways(self, detector):
        """Zero SMA (bad data) → SIDEWAYS."""
        regime = detector.detect(india_vix=15.0, nifty_price=22000, nifty_sma200=0)
        assert regime.trend == "SIDEWAYS"


# ── Position scale matrix ─────────────────────────────────────────────────────


class TestPositionScale:
    """Test the composite (VIX × trend) → scale lookup."""

    def test_low_vol_uptrend_full_gas(self, detector):
        regime = detector.detect(india_vix=10.0, nifty_price=22000, nifty_sma200=21000)
        assert regime.position_scale == 1.2

    def test_normal_uptrend_standard(self, detector):
        regime = detector.detect(india_vix=15.0, nifty_price=22000, nifty_sma200=21000)
        assert regime.position_scale == 1.0

    def test_normal_downtrend_cautious(self, detector):
        regime = detector.detect(india_vix=15.0, nifty_price=19000, nifty_sma200=20000)
        assert regime.position_scale == 0.7

    def test_high_vol_uptrend_half_size(self, detector):
        regime = detector.detect(india_vix=25.0, nifty_price=22000, nifty_sma200=21000)
        assert regime.position_scale == 0.5

    def test_crisis_any_trend_no_trade(self, detector):
        """Crisis regime should ALWAYS give 0.0 regardless of trend."""
        for nifty_price, expected_trend in [(22000, "UPTREND"), (19000, "DOWNTREND")]:
            regime = detector.detect(
                india_vix=35.0, nifty_price=nifty_price, nifty_sma200=20000,
            )
            assert regime.position_scale == 0.0
            assert regime.should_trade is False

    def test_should_trade_property(self, detector):
        """should_trade is True when scale > 0."""
        regime = detector.detect(india_vix=15.0, nifty_price=22000, nifty_sma200=21000)
        assert regime.should_trade is True

    def test_scale_matrix_completeness(self):
        """All 12 combinations must be in the matrix."""
        vix_regimes = ["LOW_VOL", "NORMAL", "HIGH_VOL", "CRISIS"]
        trends = ["UPTREND", "DOWNTREND", "SIDEWAYS"]
        for vix in vix_regimes:
            for trend in trends:
                assert (vix, trend) in _SCALE_MATRIX, f"Missing: ({vix}, {trend})"

    def test_all_regimes_return_market_regime(self, detector):
        """Every combination returns a valid MarketRegime dataclass."""
        test_cases = [
            (10.0, 22000, 21000),  # LOW_VOL + UPTREND
            (15.0, 19000, 20000),  # NORMAL + DOWNTREND
            (25.0, 20100, 20000),  # HIGH_VOL + SIDEWAYS
            (35.0, 22000, 21000),  # CRISIS + UPTREND
            (None, None, None),    # All missing
        ]
        for vix, price, sma in test_cases:
            regime = detector.detect(india_vix=vix, nifty_price=price, nifty_sma200=sma)
            assert isinstance(regime, MarketRegime)
            assert 0.0 <= regime.position_scale <= 1.2

"""Tests for ATR-based position sizing.

Validates the core formula:
    quantity = floor(risk_amount / stop_distance)
where risk_amount = equity * risk_pct * scale, stop_distance = ATR * multiplier.
"""

import math
from unittest.mock import patch

import pytest

from skopaq.risk.position_sizer import PositionSize, PositionSizer


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sizer():
    """Default sizer: 1% risk, 2× ATR multiplier."""
    return PositionSizer(risk_per_trade_pct=0.01, atr_multiplier=2.0)


@pytest.fixture
def mock_atr_vendor():
    """Patch fetch_atr to return a known value (avoid network calls)."""
    with patch("skopaq.risk.position_sizer.fetch_atr", return_value=50.0) as m:
        yield m


@pytest.fixture
def mock_atr_none():
    """Patch fetch_atr to return None (vendor unavailable)."""
    with patch("skopaq.risk.position_sizer.fetch_atr", return_value=None) as m:
        yield m


# ── Core formula tests ────────────────────────────────────────────────────────


class TestCoreFormula:
    """Verify the turtle-trader position sizing formula."""

    def test_basic_computation(self, sizer, mock_atr_vendor):
        """Standard case: 10L equity, ATR=50, price=2500.

        risk_amount  = 10,00,000 * 0.01 = 10,000 INR
        stop_distance = 50 * 2.0 = 100 INR
        quantity     = floor(10000 / 100) = 100 shares
        stop_loss    = 2500 - 100 = 2400
        """
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
        )
        assert result.quantity == 100
        assert result.stop_loss == 2400.0
        assert result.risk_amount == 10_000.0
        assert result.atr == 50.0
        assert result.atr_source == "vendor"

    def test_high_atr_reduces_position(self, sizer):
        """Higher ATR → smaller position (more volatile stock gets less size)."""
        with patch("skopaq.risk.position_sizer.fetch_atr", return_value=200.0):
            result = sizer.compute_size(
                equity=1_000_000, price=2500.0,
                symbol="RELIANCE", trade_date="2026-03-01",
            )
        # stop_distance = 200 * 2 = 400, qty = 10000/400 = 25
        assert result.quantity == 25

    def test_low_atr_increases_position(self, sizer):
        """Lower ATR → larger position (calm stock gets more size)."""
        with patch("skopaq.risk.position_sizer.fetch_atr", return_value=10.0):
            result = sizer.compute_size(
                equity=1_000_000, price=2500.0,
                symbol="RELIANCE", trade_date="2026-03-01",
            )
        # stop_distance = 10 * 2 = 20, qty = 10000/20 = 500
        assert result.quantity == 500


class TestFallbackToEstimate:
    """When vendor ATR is unavailable, use estimate (2% of price)."""

    def test_none_atr_uses_estimate(self, sizer, mock_atr_none):
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
        )
        # ATR estimate = 2500 * 0.02 = 50
        # stop_distance = 50 * 2.0 = 100
        # qty = 10000 / 100 = 100
        assert result.atr_source == "estimate"
        assert result.atr == 50.0
        assert result.quantity == 100

    def test_zero_atr_uses_estimate(self, sizer):
        with patch("skopaq.risk.position_sizer.fetch_atr", return_value=0.0):
            result = sizer.compute_size(
                equity=1_000_000, price=2500.0,
                symbol="RELIANCE", trade_date="2026-03-01",
            )
        assert result.atr_source == "estimate"

    def test_negative_atr_uses_estimate(self, sizer):
        with patch("skopaq.risk.position_sizer.fetch_atr", return_value=-5.0):
            result = sizer.compute_size(
                equity=1_000_000, price=2500.0,
                symbol="RELIANCE", trade_date="2026-03-01",
            )
        assert result.atr_source == "estimate"


class TestRegimeAndCalendarScaling:
    """Position size should shrink/grow with risk environment multipliers."""

    def test_regime_reduces_size(self, sizer, mock_atr_vendor):
        """High-vol regime (0.5) should halve the position."""
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
            regime_scale=0.5, calendar_scale=1.0,
        )
        # risk_amount = 10000 * 0.5 = 5000, qty = 5000/100 = 50
        assert result.quantity == 50

    def test_calendar_reduces_size(self, sizer, mock_atr_vendor):
        """F&O expiry (0.7) should shrink the position."""
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
            regime_scale=1.0, calendar_scale=0.7,
        )
        # risk_amount = 10000 * 0.7 = 7000, qty = 7000/100 = 70
        assert result.quantity == 70

    def test_combined_scaling(self, sizer, mock_atr_vendor):
        """Both regime (0.5) and calendar (0.7) compound."""
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
            regime_scale=0.5, calendar_scale=0.7,
        )
        # risk_amount = 10000 * 0.35 = 3500, qty = 3500/100 = 35
        assert result.quantity == 35

    def test_zero_scale_gives_minimum_qty(self, sizer, mock_atr_vendor):
        """Crisis regime (0.0) should give minimum quantity."""
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
            regime_scale=0.0, calendar_scale=1.0,
        )
        # risk_amount = 0, qty = max(1, floor(0)) = 1
        assert result.quantity == 1  # min_quantity

    def test_scale_clamped_at_1_5(self, sizer, mock_atr_vendor):
        """Effective scale cannot exceed 1.5 (prevents runaway sizing)."""
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
            regime_scale=1.2, calendar_scale=1.0,
        )
        # effective_scale = min(1.2*1.0, 1.5) = 1.2
        # risk_amount = 10000 * 1.2 = 12000, qty = 12000/100 = 120
        assert result.quantity == 120


class TestEdgeCases:
    """Guard against degenerate inputs."""

    def test_zero_equity_returns_minimum(self, sizer, mock_atr_vendor):
        result = sizer.compute_size(
            equity=0, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
        )
        assert result.quantity == 1

    def test_negative_equity_returns_minimum(self, sizer, mock_atr_vendor):
        result = sizer.compute_size(
            equity=-50000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
        )
        assert result.quantity == 1

    def test_zero_price_returns_minimum(self, sizer, mock_atr_vendor):
        result = sizer.compute_size(
            equity=1_000_000, price=0,
            symbol="RELIANCE", trade_date="2026-03-01",
        )
        assert result.quantity == 1

    def test_very_low_atr_clamped(self, sizer):
        """ATR stop distance must be at least 0.5% of price."""
        with patch("skopaq.risk.position_sizer.fetch_atr", return_value=0.01):
            result = sizer.compute_size(
                equity=1_000_000, price=2500.0,
                symbol="RELIANCE", trade_date="2026-03-01",
            )
        # stop_distance = max(0.01 * 2.0 = 0.02, 2500 * 0.005 = 12.5) = 12.5
        # qty = 10000 / 12.5 = 800
        assert result.quantity == 800
        # Stop loss = 2500 - 12.5 = 2487.5
        assert result.stop_loss == 2487.5

    def test_stop_loss_is_below_entry(self, sizer, mock_atr_vendor):
        """Stop loss should always be below entry price for BUY."""
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
        )
        assert result.stop_loss < 2500.0

    def test_quantity_is_always_int(self, sizer, mock_atr_vendor):
        """Position size must be a whole number of shares."""
        result = sizer.compute_size(
            equity=777_777, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
        )
        assert isinstance(result.quantity, int)


class TestCustomParameters:
    """Verify non-default risk parameters work correctly."""

    def test_higher_risk_pct(self, mock_atr_vendor):
        sizer = PositionSizer(risk_per_trade_pct=0.02)  # 2% risk
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
        )
        # risk = 20000, stop = 100, qty = 200
        assert result.quantity == 200

    def test_higher_atr_multiplier(self, mock_atr_vendor):
        sizer = PositionSizer(atr_multiplier=3.0)  # Wider stop
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
        )
        # stop_distance = 50 * 3.0 = 150, qty = 10000/150 = 66
        assert result.quantity == 66


class TestConfidenceScaling:
    """Position size should scale with AI confidence."""

    def test_full_confidence_no_reduction(self, sizer, mock_atr_vendor):
        """confidence_scale=1.0 (100% confidence) → same as baseline."""
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
            confidence_scale=1.0,
        )
        assert result.quantity == 100  # Same as baseline

    def test_half_confidence_reduces_size(self, sizer, mock_atr_vendor):
        """confidence_scale=0.75 (50% confidence) → 75% of baseline."""
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
            confidence_scale=0.75,
        )
        # risk_amount = 10000 * 0.75 = 7500, qty = 7500/100 = 75
        assert result.quantity == 75

    def test_zero_confidence_still_trades(self, sizer, mock_atr_vendor):
        """confidence_scale=0.5 (0% confidence floor) → half size."""
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
            confidence_scale=0.5,
        )
        # risk_amount = 10000 * 0.5 = 5000, qty = 5000/100 = 50
        assert result.quantity == 50

    def test_confidence_compounds_with_regime(self, sizer, mock_atr_vendor):
        """confidence_scale * regime_scale compound multiplicatively."""
        result = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
            regime_scale=0.5, confidence_scale=0.75,
        )
        # effective = 0.5 * 1.0 * 0.75 = 0.375
        # risk = 10000 * 0.375 = 3750, qty = 3750/100 = 37
        assert result.quantity == 37

    def test_default_confidence_scale_is_neutral(self, sizer, mock_atr_vendor):
        """Omitting confidence_scale should be identical to baseline."""
        with_default = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
        )
        with_explicit = sizer.compute_size(
            equity=1_000_000, price=2500.0,
            symbol="RELIANCE", trade_date="2026-03-01",
            confidence_scale=1.0,
        )
        assert with_default.quantity == with_explicit.quantity

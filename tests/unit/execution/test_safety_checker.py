"""Tests for the pre-trade safety checker.

Each safety rule gets its own test to ensure it fires at the right threshold.
"""

import pytest
from datetime import datetime, time, timezone, timedelta
from unittest.mock import patch

from skopaq.broker.models import (
    Exchange,
    Funds,
    OrderRequest,
    OrderType,
    Position,
    Product,
    Side,
    TradingSignal,
)
from skopaq.constants import SafetyRules
from skopaq.execution.safety_checker import SafetyChecker


@pytest.fixture
def rules():
    """Custom rules for testing (can override frozen defaults)."""
    return SafetyRules(
        max_position_pct=0.15,
        max_daily_loss_pct=0.03,
        max_weekly_loss_pct=0.07,
        max_monthly_loss_pct=0.12,
        max_open_positions=3,
        max_order_value_inr=100_000,
        max_orders_per_minute=5,
        require_stop_loss=True,
        min_stop_loss_pct=0.02,
        no_naked_option_selling=True,
        market_hours_only=False,  # Disable for testing
        cool_down_after_loss_minutes=5,
    )


@pytest.fixture
def checker(rules):
    return SafetyChecker(rules=rules)


@pytest.fixture
def funds():
    return Funds(available_cash=500_000, available_margin=500_000, total_collateral=500_000)


@pytest.fixture
def signal_with_sl():
    return TradingSignal(
        symbol="RELIANCE", action="BUY", confidence=70,
        entry_price=2500, stop_loss=2450,
    )


@pytest.fixture
def signal_no_sl():
    return TradingSignal(
        symbol="RELIANCE", action="BUY", confidence=70,
        entry_price=2500,
    )


def _buy_order(symbol="RELIANCE", qty=10, price=2500.0):
    return OrderRequest(
        symbol=symbol, exchange=Exchange.NSE, side=Side.BUY,
        quantity=qty, order_type=OrderType.LIMIT, price=price,
        product=Product.CNC,
    )


def _sell_order(symbol="RELIANCE", qty=10, price=2500.0):
    return OrderRequest(
        symbol=symbol, exchange=Exchange.NSE, side=Side.SELL,
        quantity=qty, order_type=OrderType.LIMIT, price=price,
        product=Product.CNC,
    )


class TestPositionSize:
    def test_within_limit_passes(self, checker, funds, signal_with_sl):
        # 10 * 2500 = 25000 = 5% of 500,000 < 15%
        order = _buy_order(qty=10, price=2500)
        result = checker.validate(order, signal_with_sl, [], funds, 500_000)
        assert result.passed

    def test_exceeds_limit_rejected(self, checker, funds, signal_with_sl):
        # 40 * 2500 = 100,000 = 20% of 500,000 > 15%
        order = _buy_order(qty=40, price=2500)
        result = checker.validate(order, signal_with_sl, [], funds, 500_000)
        assert not result.passed
        assert any("Position size" in r for r in result.rejections)


class TestOrderValue:
    def test_within_cap_passes(self, checker, funds, signal_with_sl):
        # 10 * 2500 = 25,000 < 100,000
        order = _buy_order(qty=10, price=2500)
        result = checker.validate(order, signal_with_sl, [], funds, 1_000_000)
        assert result.passed

    def test_exceeds_cap_rejected(self, checker, funds, signal_with_sl):
        # 50 * 2500 = 125,000 > 100,000
        order = _buy_order(qty=50, price=2500)
        result = checker.validate(order, signal_with_sl, [], funds, 1_000_000)
        assert not result.passed
        assert any("Order value" in r for r in result.rejections)


class TestMaxPositions:
    def test_under_limit_passes(self, checker, funds, signal_with_sl):
        positions = [
            Position(symbol="TCS", exchange=Exchange.NSE, product=Product.CNC,
                     quantity=10, average_price=3000, last_price=3000, pnl=0, day_pnl=0),
            Position(symbol="INFY", exchange=Exchange.NSE, product=Product.CNC,
                     quantity=5, average_price=1500, last_price=1500, pnl=0, day_pnl=0),
        ]
        order = _buy_order("RELIANCE", qty=10, price=2500)
        result = checker.validate(order, signal_with_sl, positions, funds, 1_000_000)
        assert result.passed

    def test_at_limit_rejected(self, checker, funds, signal_with_sl):
        positions = [
            Position(symbol=s, exchange=Exchange.NSE, product=Product.CNC,
                     quantity=10, average_price=100, last_price=100, pnl=0, day_pnl=0)
            for s in ["TCS", "INFY", "HDFC"]
        ]
        order = _buy_order("RELIANCE", qty=1, price=100)  # New symbol
        result = checker.validate(order, signal_with_sl, positions, funds, 1_000_000)
        assert not result.passed
        assert any("open positions" in r for r in result.rejections)

    def test_adding_to_existing_position_passes(self, checker, funds, signal_with_sl):
        """Buying more of an existing position should NOT count as a new position."""
        positions = [
            Position(symbol=s, exchange=Exchange.NSE, product=Product.CNC,
                     quantity=10, average_price=100, last_price=100, pnl=0, day_pnl=0)
            for s in ["TCS", "INFY", "RELIANCE"]
        ]
        order = _buy_order("RELIANCE", qty=5, price=100)  # Same symbol
        result = checker.validate(order, signal_with_sl, positions, funds, 1_000_000)
        assert result.passed


class TestStopLoss:
    def test_buy_with_stop_loss_passes(self, checker, funds, signal_with_sl):
        order = _buy_order(qty=1, price=100)
        result = checker.validate(order, signal_with_sl, [], funds, 1_000_000)
        assert result.passed

    def test_buy_without_stop_loss_rejected(self, checker, funds, signal_no_sl):
        order = _buy_order(qty=1, price=100)
        result = checker.validate(order, signal_no_sl, [], funds, 1_000_000)
        assert not result.passed
        assert any("stop-loss" in r.lower() for r in result.rejections)

    def test_sell_without_stop_loss_passes(self, checker, funds, signal_no_sl):
        """Sell orders don't need a stop loss."""
        order = _sell_order(qty=1, price=100)
        result = checker.validate(order, signal_no_sl, [], funds, 1_000_000)
        assert result.passed


class TestDailyLoss:
    def test_under_threshold_passes(self, checker, funds, signal_with_sl):
        # Record a small loss: 1% of 500k = 5000
        checker.record_pnl(-5000)
        # Clear the cool-down so we isolate the daily loss check
        checker._last_loss_time = None
        order = _buy_order(qty=1, price=100)
        result = checker.validate(order, signal_with_sl, [], funds, 500_000)
        assert result.passed  # 1% < 3%

    def test_exceeds_threshold_rejected(self, checker, funds, signal_with_sl):
        # Record a 4% loss: 20000 of 500k
        checker.record_pnl(-20_000)
        order = _buy_order(qty=1, price=100)
        result = checker.validate(order, signal_with_sl, [], funds, 500_000)
        assert not result.passed
        assert any("Daily loss" in r for r in result.rejections)


class TestOrderRate:
    def test_under_rate_passes(self, checker, funds, signal_with_sl):
        order = _buy_order(qty=1, price=100)
        for _ in range(4):
            result = checker.validate(order, signal_with_sl, [], funds, 1_000_000)
            assert result.passed

    def test_exceeds_rate_rejected(self, checker, funds, signal_with_sl):
        order = _buy_order(qty=1, price=100)
        for _ in range(5):
            checker.validate(order, signal_with_sl, [], funds, 1_000_000)
        result = checker.validate(order, signal_with_sl, [], funds, 1_000_000)
        assert not result.passed
        assert any("Rate limit" in r for r in result.rejections)


class TestCoolDown:
    def test_no_loss_no_cooldown(self, checker, funds, signal_with_sl):
        order = _buy_order(qty=1, price=100)
        result = checker.validate(order, signal_with_sl, [], funds, 1_000_000)
        assert result.passed

    def test_loss_triggers_cooldown(self, checker, funds, signal_with_sl):
        checker.record_pnl(-100)
        order = _buy_order(qty=1, price=100)
        result = checker.validate(order, signal_with_sl, [], funds, 1_000_000)
        assert not result.passed
        assert any("Cool-down" in r for r in result.rejections)


class TestNakedOptions:
    def test_selling_option_rejected(self, checker, funds):
        order = OrderRequest(
            symbol="NIFTY23DEC21000CE", exchange=Exchange.NSE, side=Side.SELL,
            quantity=50, order_type=OrderType.LIMIT, price=200,
            product=Product.NRML,
        )
        result = checker.validate(order, None, [], funds, 1_000_000)
        assert not result.passed
        assert any("Naked option" in r for r in result.rejections)

    def test_buying_option_passes(self, checker, funds, signal_with_sl):
        order = OrderRequest(
            symbol="NIFTY23DEC21000CE", exchange=Exchange.NSE, side=Side.BUY,
            quantity=50, order_type=OrderType.LIMIT, price=200,
            product=Product.NRML,
        )
        result = checker.validate(order, signal_with_sl, [], funds, 1_000_000)
        assert result.passed


class TestInsufficientFunds:
    def test_buy_within_margin_passes(self, checker, signal_with_sl):
        funds = Funds(available_margin=50_000)
        order = _buy_order(qty=10, price=2500)  # 25,000
        result = checker.validate(order, signal_with_sl, [], funds, 500_000)
        assert result.passed

    def test_buy_exceeds_margin_rejected(self, checker, signal_with_sl):
        funds = Funds(available_margin=10_000)
        order = _buy_order(qty=10, price=2500)  # 25,000 > 10,000
        result = checker.validate(order, signal_with_sl, [], funds, 500_000)
        assert not result.passed
        assert any("Insufficient margin" in r for r in result.rejections)


class TestReset:
    def test_daily_reset_clears_pnl(self, checker, funds, signal_with_sl):
        checker.record_pnl(-20_000)
        checker.reset_daily()
        order = _buy_order(qty=1, price=100)
        result = checker.validate(order, signal_with_sl, [], funds, 500_000)
        assert result.passed  # Daily loss reset

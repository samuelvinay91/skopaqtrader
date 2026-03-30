"""Tests for Executor — signal-to-order translation and safety pipeline.

Covers: _build_order, _cap_quantity, execute_signal pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skopaq.broker.models import (
    ExecutionResult,
    Exchange,
    Funds,
    OrderRequest,
    OrderResponse,
    OrderType,
    Position,
    Product,
    Side,
    TradingSignal,
)
from skopaq.broker.paper_engine import PaperEngine
from skopaq.execution.executor import Executor
from skopaq.execution.order_router import OrderRouter
from skopaq.execution.safety_checker import SafetyChecker


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_executor(
    mode="paper", rules=None, sizer=None, product="CNC",
) -> tuple[Executor, PaperEngine, OrderRouter]:
    """Build a minimal Executor stack for testing."""
    from skopaq.constants import PAPER_SAFETY_RULES

    config = MagicMock()
    config.trading_mode = mode
    config.broker = "indstocks"
    config.max_sector_concentration_pct = 0.40

    paper = PaperEngine(initial_capital=1_000_000, slippage_pct=0.0, brokerage=0.0)
    router = OrderRouter(config, paper)
    safety = SafetyChecker(
        rules=rules or PAPER_SAFETY_RULES,
        max_sector_concentration_pct=0.40,
    )
    executor = Executor(router, safety, position_sizer=sizer, product=product)
    return executor, paper, router


def _buy_signal(symbol="RELIANCE", price=2500.0, qty=10, confidence=70):
    return TradingSignal(
        symbol=symbol,
        action="BUY",
        confidence=confidence,
        entry_price=price,
        stop_loss=price * 0.96,
        quantity=Decimal(qty),
    )


def _sell_signal(symbol="RELIANCE", price=2500.0, qty=10, confidence=70):
    return TradingSignal(
        symbol=symbol,
        action="SELL",
        confidence=confidence,
        entry_price=price,
        quantity=Decimal(qty),
    )


def _hold_signal(symbol="RELIANCE"):
    return TradingSignal(
        symbol=symbol,
        action="HOLD",
        confidence=50,
    )


# ── _build_order tests ──────────────────────────────────────────────────────


class TestBuildOrder:
    def test_buy_signal_creates_buy_order(self):
        executor, _, _ = _make_executor()
        signal = _buy_signal()
        order = executor._build_order(signal)

        assert order is not None
        assert order.side == Side.BUY
        assert order.symbol == "RELIANCE"
        assert order.quantity == Decimal("10")
        assert order.order_type == OrderType.LIMIT
        assert order.price == 2500.0
        assert order.product == Product.CNC
        assert "skopaq-70" in order.tag

    def test_sell_signal_creates_sell_order(self):
        executor, _, _ = _make_executor()
        signal = _sell_signal()
        order = executor._build_order(signal)

        assert order is not None
        assert order.side == Side.SELL
        assert order.quantity == Decimal("10")

    def test_hold_signal_returns_none(self):
        executor, _, _ = _make_executor()
        signal = _hold_signal()
        order = executor._build_order(signal)
        assert order is None

    def test_no_entry_price_creates_market_order(self):
        executor, _, _ = _make_executor()
        signal = TradingSignal(
            symbol="RELIANCE", action="BUY", confidence=70,
            entry_price=None, quantity=Decimal(5),
        )
        order = executor._build_order(signal)

        assert order is not None
        assert order.order_type == OrderType.MARKET
        assert order.price is None

    def test_buy_with_stop_loss_sets_trigger_price(self):
        executor, _, _ = _make_executor()
        signal = _buy_signal(price=2500, qty=10)
        signal.stop_loss = 2400.0
        order = executor._build_order(signal)

        assert order.trigger_price == 2400.0

    def test_sell_does_not_set_trigger_price(self):
        executor, _, _ = _make_executor()
        signal = _sell_signal()
        signal.stop_loss = 2400.0
        order = executor._build_order(signal)

        assert order.trigger_price is None

    def test_default_quantity_is_1(self):
        executor, _, _ = _make_executor()
        signal = TradingSignal(
            symbol="RELIANCE", action="BUY", confidence=70,
            entry_price=2500.0, quantity=None,
        )
        order = executor._build_order(signal)
        assert order.quantity == 1

    def test_exchange_from_signal(self):
        executor, _, _ = _make_executor()
        signal = TradingSignal(
            symbol="RELIANCE", action="BUY", confidence=70,
            exchange=Exchange.BSE, entry_price=2500.0, quantity=Decimal(5),
        )
        order = executor._build_order(signal)
        assert order.exchange == Exchange.BSE


# ── _cap_quantity tests ──────────────────────────────────────────────────────


class TestCapQuantity:
    def test_respects_max_lots(self):
        executor, _, _ = _make_executor()
        # PAPER_SAFETY_RULES.max_lots_per_position = 5
        capped = executor._cap_quantity(raw_qty=100, price=100.0, equity=1_000_000)
        assert capped <= 5

    def test_respects_max_position_pct(self):
        executor, _, _ = _make_executor()
        # max_position_pct=0.15 → 150K max on 1M equity → at 2500/share = 60 max
        capped = executor._cap_quantity(raw_qty=100, price=2500.0, equity=1_000_000)
        assert capped <= 60

    def test_respects_max_order_value(self):
        executor, _, _ = _make_executor()
        # PAPER_SAFETY_RULES.max_order_value_inr = 500_000
        # At 100K/share → max 5 shares
        capped = executor._cap_quantity(raw_qty=100, price=100_000.0, equity=10_000_000)
        assert capped <= 5

    def test_minimum_is_1(self):
        executor, _, _ = _make_executor()
        capped = executor._cap_quantity(raw_qty=0, price=2500.0, equity=1_000_000)
        assert capped == 1

    def test_zero_price_returns_raw_capped(self):
        executor, _, _ = _make_executor()
        capped = executor._cap_quantity(raw_qty=3, price=0.0, equity=1_000_000)
        assert capped == 3  # Only max_lots cap applies


# ── execute_signal pipeline tests ────────────────────────────────────────────


@pytest.mark.asyncio
class TestExecuteSignal:
    async def test_buy_fills_in_paper_mode(self):
        executor, paper, _ = _make_executor()
        from skopaq.broker.models import Quote
        paper.update_quote(Quote(
            symbol="RELIANCE", ltp=2500, bid=2499, ask=2501,
        ))

        signal = _buy_signal("RELIANCE", price=2500, qty=5)
        result = await executor.execute_signal(signal)

        assert result.success
        assert result.mode == "paper"

    async def test_hold_signal_rejected(self):
        executor, _, _ = _make_executor()
        signal = _hold_signal()
        result = await executor.execute_signal(signal)

        assert not result.success
        assert "Cannot build order" in result.rejection_reason

    async def test_sell_records_pnl(self):
        executor, paper, _ = _make_executor()
        from skopaq.broker.models import Quote
        paper.update_quote(Quote(
            symbol="RELIANCE", ltp=2600, bid=2599, ask=2601,
        ))

        # First buy
        buy_signal = _buy_signal("RELIANCE", price=2600, qty=5)
        await executor.execute_signal(buy_signal)

        # Then sell at higher price
        paper.update_quote(Quote(
            symbol="RELIANCE", ltp=2700, bid=2699, ask=2701,
        ))
        sell_signal = _sell_signal("RELIANCE", price=2700, qty=5)
        result = await executor.execute_signal(sell_signal)

        assert result.success

    async def test_safety_rejection(self):
        """Order exceeding safety limits should be rejected."""
        from skopaq.constants import PAPER_SAFETY_RULES

        executor, paper, _ = _make_executor()
        from skopaq.broker.models import Quote
        paper.update_quote(Quote(
            symbol="RELIANCE", ltp=2500, bid=2499, ask=2501,
        ))

        # Try to buy way more than max_order_value allows
        signal = TradingSignal(
            symbol="RELIANCE", action="BUY", confidence=70,
            entry_price=2500.0,
            stop_loss=2400.0,
            quantity=Decimal(10000),  # 10000 * 2500 = 25M >> 500K limit
        )
        result = await executor.execute_signal(signal)

        assert not result.success
        assert not result.safety_passed

    async def test_entry_price_resolved_from_yfinance(self):
        """When entry_price is missing, executor tries yfinance."""
        executor, paper, _ = _make_executor()
        from skopaq.broker.models import Quote
        paper.update_quote(Quote(
            symbol="RELIANCE", ltp=2500, bid=2499, ask=2501,
        ))

        signal = TradingSignal(
            symbol="RELIANCE", action="BUY", confidence=70,
            entry_price=None,  # Missing
            stop_loss=2400.0,
            quantity=Decimal(5),
        )

        with patch.object(
            Executor, "_fetch_current_price", return_value=2500.0,
        ):
            result = await executor.execute_signal(signal)

        assert signal.entry_price == 2500.0  # Should have been resolved


# ── Intraday (MIS) product tests ─────────────────────────────────────────


class TestIntradayProduct:
    def test_intraday_executor_uses_mis(self):
        """Executor with product=MIS should build intraday orders."""
        executor, _, _ = _make_executor(product="MIS")
        signal = _buy_signal()
        order = executor._build_order(signal)
        # MIS maps to Product.INTRADAY (value "INTRADAY")
        assert order.product.value == "INTRADAY"

    def test_delivery_executor_uses_cnc(self):
        """Executor with default product=CNC should build CNC orders."""
        executor, _, _ = _make_executor(product="CNC")
        signal = _buy_signal()
        order = executor._build_order(signal)
        assert order.product == Product.CNC

    def test_nrml_product(self):
        """Executor with product=NRML for F&O."""
        executor, _, _ = _make_executor(product="NRML")
        signal = _buy_signal()
        order = executor._build_order(signal)
        # NRML maps to Product.MARGIN (value "MARGIN")
        assert order.product.value == "MARGIN"

    def test_product_persists_across_orders(self):
        """Product should be the same for all orders from the same executor."""
        executor, _, _ = _make_executor(product="MIS")
        buy_order = executor._build_order(_buy_signal())
        sell_order = executor._build_order(_sell_signal())
        assert buy_order.product.value == "INTRADAY"
        assert sell_order.product.value == "INTRADAY"


class TestIntradaySafetyRules:
    def test_intraday_rules_require_market_hours(self):
        from skopaq.constants import INTRADAY_SAFETY_RULES
        assert INTRADAY_SAFETY_RULES.market_hours_only is True

    def test_intraday_rules_require_stop_loss(self):
        from skopaq.constants import INTRADAY_SAFETY_RULES
        assert INTRADAY_SAFETY_RULES.require_stop_loss is True

    def test_intraday_rules_tighter_min_stop(self):
        from skopaq.constants import INTRADAY_SAFETY_RULES, SAFETY_RULES
        assert INTRADAY_SAFETY_RULES.min_stop_loss_pct < SAFETY_RULES.min_stop_loss_pct

    def test_intraday_paper_relaxes_timing(self):
        from skopaq.constants import INTRADAY_PAPER_SAFETY_RULES
        assert INTRADAY_PAPER_SAFETY_RULES.market_hours_only is False
        assert INTRADAY_PAPER_SAFETY_RULES.require_stop_loss is False

    def test_intraday_tighter_daily_loss(self):
        from skopaq.constants import INTRADAY_SAFETY_RULES, SAFETY_RULES
        assert INTRADAY_SAFETY_RULES.max_daily_loss_pct < SAFETY_RULES.max_daily_loss_pct

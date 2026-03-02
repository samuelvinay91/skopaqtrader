"""Tests for the paper trading engine."""

import pytest

from skopaq.broker.models import (
    Exchange,
    OrderRequest,
    OrderStatus,
    OrderType,
    Product,
    Quote,
    Side,
)
from skopaq.broker.paper_engine import PaperEngine


@pytest.fixture
def engine():
    return PaperEngine(initial_capital=100_000.0, slippage_pct=0.0, brokerage=0.0)


@pytest.fixture
def reliance_quote():
    return Quote(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        ltp=2500.0,
        bid=2499.0,
        ask=2501.0,
        volume=1_000_000,
    )


def _market_buy(symbol="RELIANCE", qty=10):
    return OrderRequest(
        symbol=symbol,
        exchange=Exchange.NSE,
        side=Side.BUY,
        quantity=qty,
        order_type=OrderType.MARKET,
        product=Product.CNC,
    )


def _market_sell(symbol="RELIANCE", qty=10):
    return OrderRequest(
        symbol=symbol,
        exchange=Exchange.NSE,
        side=Side.SELL,
        quantity=qty,
        order_type=OrderType.MARKET,
        product=Product.CNC,
    )


class TestPaperEngine:
    def test_no_quote_rejects_order(self, engine):
        result = engine.execute_order(_market_buy())
        assert not result.success
        assert "No quote" in result.rejection_reason

    def test_market_buy_fills(self, engine, reliance_quote):
        engine.update_quote(reliance_quote)
        result = engine.execute_order(_market_buy(qty=10))
        assert result.success
        assert result.mode == "paper"
        assert result.order.status == OrderStatus.COMPLETE
        # Fill at ask for buys (with zero slippage)
        assert result.fill_price == 2501.0

    def test_market_sell_fills(self, engine, reliance_quote):
        engine.update_quote(reliance_quote)
        # First buy
        engine.execute_order(_market_buy(qty=10))
        # Then sell
        result = engine.execute_order(_market_sell(qty=10))
        assert result.success
        # Fill at bid for sells
        assert result.fill_price == 2499.0

    def test_position_tracking(self, engine, reliance_quote):
        engine.update_quote(reliance_quote)
        engine.execute_order(_market_buy(qty=10))
        positions = engine.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "RELIANCE"
        assert positions[0].quantity == 10

    def test_position_closes_on_sell(self, engine, reliance_quote):
        engine.update_quote(reliance_quote)
        engine.execute_order(_market_buy(qty=10))
        engine.execute_order(_market_sell(qty=10))
        positions = engine.get_positions()
        assert len(positions) == 0

    def test_cash_decreases_on_buy(self, engine, reliance_quote):
        engine.update_quote(reliance_quote)
        engine.execute_order(_market_buy(qty=10))
        funds = engine.get_funds()
        # 100000 - (2501 * 10) = 74990
        assert funds.available_cash == pytest.approx(100_000 - 2501.0 * 10, abs=1)

    def test_insufficient_funds_rejected(self, engine, reliance_quote):
        engine.update_quote(reliance_quote)
        # Try to buy 100 shares at ~2501 = 250,100 > 100,000 capital
        result = engine.execute_order(_market_buy(qty=100))
        assert not result.success
        assert "Insufficient funds" in result.rejection_reason

    def test_limit_buy_fills_when_price_favorable(self, engine, reliance_quote):
        engine.update_quote(reliance_quote)
        order = OrderRequest(
            symbol="RELIANCE", exchange=Exchange.NSE, side=Side.BUY,
            quantity=5, order_type=OrderType.LIMIT, price=2600.0,
            product=Product.CNC,
        )
        result = engine.execute_order(order)
        assert result.success  # LTP 2500 <= limit 2600

    def test_limit_buy_rejects_when_price_unfavorable(self, engine, reliance_quote):
        engine.update_quote(reliance_quote)
        order = OrderRequest(
            symbol="RELIANCE", exchange=Exchange.NSE, side=Side.BUY,
            quantity=5, order_type=OrderType.LIMIT, price=2400.0,
            product=Product.CNC,
        )
        result = engine.execute_order(order)
        assert not result.success  # LTP 2500 > limit 2400

    def test_snapshot(self, engine, reliance_quote):
        engine.update_quote(reliance_quote)
        engine.execute_order(_market_buy(qty=10))
        snapshot = engine.get_snapshot()
        assert float(snapshot.cash) < 100_000
        assert float(snapshot.positions_value) > 0
        assert len(snapshot.positions) == 1

    def test_day_reset(self, engine, reliance_quote):
        engine.update_quote(reliance_quote)
        engine.execute_order(_market_buy(qty=5))
        assert len(engine.get_orders()) == 1
        engine.reset_day()
        assert len(engine.get_orders()) == 0

    def test_brokerage_deducted(self):
        engine = PaperEngine(initial_capital=100_000, slippage_pct=0.0, brokerage=20.0)
        quote = Quote(symbol="TCS", exchange=Exchange.NSE, ltp=3000, bid=3000, ask=3000)
        engine.update_quote(quote)
        order = _market_buy("TCS", qty=1)
        result = engine.execute_order(order)
        assert result.success
        assert result.brokerage == 20.0
        funds = engine.get_funds()
        # 100000 - 3000 - 20 = 96980
        assert funds.available_cash == pytest.approx(96980, abs=1)

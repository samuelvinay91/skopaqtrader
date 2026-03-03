"""Tests for the paper trading engine."""

from decimal import Decimal

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


# ── Crypto-specific tests ────────────────────────────────────────────────────


def _crypto_buy(symbol="BTCUSDT", qty=Decimal("0.01")):
    return OrderRequest(
        symbol=symbol,
        exchange=Exchange.BINANCE,
        side=Side.BUY,
        quantity=qty,
        order_type=OrderType.MARKET,
        product=Product.CNC,
    )


def _crypto_sell(symbol="BTCUSDT", qty=Decimal("0.01")):
    return OrderRequest(
        symbol=symbol,
        exchange=Exchange.BINANCE,
        side=Side.SELL,
        quantity=qty,
        order_type=OrderType.MARKET,
        product=Product.CNC,
    )


@pytest.fixture
def crypto_engine():
    """Paper engine configured for crypto (percentage brokerage, USDT)."""
    return PaperEngine(
        initial_capital=10_000.0,
        slippage_pct=0.0,
        brokerage=0.0,
        brokerage_pct=0.001,  # 0.1% Binance spot fee
        currency_label="USDT",
    )


@pytest.fixture
def btc_quote():
    return Quote(
        symbol="BTCUSDT",
        exchange=Exchange.BINANCE,
        ltp=67000.0,
        bid=66999.0,
        ask=67001.0,
        volume=50_000,
    )


class TestCryptoPaperEngine:
    def test_percentage_brokerage(self, crypto_engine, btc_quote):
        """Crypto engine uses percentage-based brokerage (0.1% of order value)."""
        crypto_engine.update_quote(btc_quote)
        result = crypto_engine.execute_order(_crypto_buy(qty=Decimal("0.01")))
        assert result.success
        # Order value = 67001 * 0.01 = 670.01
        # Brokerage = 670.01 * 0.001 = 0.67001
        assert result.brokerage == pytest.approx(0.67, abs=0.01)

    def test_fractional_quantity_fills(self, crypto_engine, btc_quote):
        """Fractional quantities (0.001 BTC) fill correctly."""
        crypto_engine.update_quote(btc_quote)
        result = crypto_engine.execute_order(_crypto_buy(qty=Decimal("0.001")))
        assert result.success
        positions = crypto_engine.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == Decimal("0.001")

    def test_crypto_buy_sell_cycle(self, crypto_engine, btc_quote):
        """Full buy/sell cycle with crypto fractional quantities."""
        crypto_engine.update_quote(btc_quote)

        # Buy 0.1 BTC
        buy = crypto_engine.execute_order(_crypto_buy(qty=Decimal("0.1")))
        assert buy.success
        assert len(crypto_engine.get_positions()) == 1

        # Sell 0.1 BTC
        sell = crypto_engine.execute_order(_crypto_sell(qty=Decimal("0.1")))
        assert sell.success
        assert len(crypto_engine.get_positions()) == 0

    def test_crypto_insufficient_funds(self, crypto_engine, btc_quote):
        """Cannot buy more crypto than capital allows."""
        crypto_engine.update_quote(btc_quote)
        # 1 BTC = ~67001 USDT, capital = 10000 USDT
        result = crypto_engine.execute_order(_crypto_buy(qty=Decimal("1")))
        assert not result.success
        assert "Insufficient funds" in result.rejection_reason

    def test_crypto_position_averaging(self, crypto_engine, btc_quote):
        """Multiple buys average the position price correctly."""
        crypto_engine.update_quote(btc_quote)

        crypto_engine.execute_order(_crypto_buy(qty=Decimal("0.01")))
        crypto_engine.execute_order(_crypto_buy(qty=Decimal("0.01")))

        positions = crypto_engine.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == Decimal("0.02")
        # Average price should be ~67001 (ask price, zero slippage)
        assert positions[0].average_price == pytest.approx(67001.0, abs=1)

    def test_currency_label_in_rejection(self, crypto_engine, btc_quote):
        """Rejection message shows USDT currency label."""
        crypto_engine.update_quote(btc_quote)
        result = crypto_engine.execute_order(_crypto_buy(qty=Decimal("1")))
        assert "USDT" in result.rejection_reason

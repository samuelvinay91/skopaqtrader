"""Tests for OrderRouter dispatch logic — async paper path and broker selection.

Covers:
- Async paper execution with MarketDataProvider
- Sync paper fallback without provider
- Live dispatch to Kite or INDstocks
- get_orders unified interface
- CLI _create_live_client factory
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from skopaq.broker.models import (
    Exchange,
    ExecutionResult,
    Funds,
    OrderRequest,
    OrderResponse,
    OrderType,
    Position,
    Product,
    Quote,
    Side,
    TradingSignal,
)
from skopaq.broker.paper_engine import PaperEngine
from skopaq.execution.order_router import OrderRouter


def _config(mode="paper", broker="indstocks"):
    cfg = MagicMock()
    cfg.trading_mode = mode
    cfg.broker = broker
    return cfg


def _buy_order(symbol="RELIANCE"):
    return OrderRequest(
        symbol=symbol, side=Side.BUY, quantity=Decimal("10"),
        price=2500.0, order_type=OrderType.LIMIT, product=Product.CNC,
    )


def _quote(symbol="RELIANCE", ltp=2500.0):
    return Quote(symbol=symbol, ltp=ltp, bid=ltp - 1, ask=ltp + 1)


# ── Async paper dispatch ────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAsyncPaperDispatch:
    async def test_with_market_data_calls_async(self):
        """When paper engine has MarketDataProvider, uses execute_order_async."""
        provider = AsyncMock()
        provider.inject_quote = MagicMock()  # sync method
        provider.get_quote = AsyncMock(return_value=_quote("RELIANCE", 2500))

        paper = PaperEngine(
            initial_capital=1_000_000, slippage_pct=0.0, brokerage=0.0,
            market_data=provider,
        )
        paper.update_quote(_quote("RELIANCE", 2500))

        router = OrderRouter(_config("paper"), paper)
        result = await router.execute(_buy_order())

        assert result.success
        assert result.mode == "paper"
        # Verify provider was called for fresh quote
        provider.get_quote.assert_called_with("RELIANCE")

    async def test_without_market_data_calls_sync(self):
        """Without MarketDataProvider, uses synchronous execute_order."""
        paper = PaperEngine(
            initial_capital=1_000_000, slippage_pct=0.0, brokerage=0.0,
        )
        paper.update_quote(_quote("RELIANCE", 2500))

        router = OrderRouter(_config("paper"), paper)
        result = await router.execute(_buy_order())

        assert result.success
        assert result.mode == "paper"


# ── Live dispatch ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestLiveDispatch:
    async def test_live_kite_no_security_id_resolution(self):
        """Kite broker should NOT resolve security_id (only INDstocks does)."""
        config = _config("live", "kite")
        paper = PaperEngine()

        live = AsyncMock()
        live.place_order = AsyncMock(return_value=OrderResponse(
            order_id="K123", status="PENDING",
        ))

        router = OrderRouter(config, paper, live_client=live)
        order = _buy_order()
        result = await router.execute(order)

        assert result.success
        assert result.mode == "live"
        live.place_order.assert_called_once_with(order)
        # security_id should NOT have been resolved for Kite
        assert order.security_id == ""

    async def test_live_indstocks_resolves_security_id(self):
        """INDstocks broker should resolve security_id before placing."""
        from unittest.mock import patch

        config = _config("live", "indstocks")
        paper = PaperEngine()

        live = AsyncMock()
        live.place_order = AsyncMock(return_value=OrderResponse(
            order_id="I456", status="PENDING",
        ))

        router = OrderRouter(config, paper, live_client=live)
        order = _buy_order()
        assert order.security_id == ""

        with patch(
            "skopaq.broker.scrip_resolver.resolve_security_id",
            new_callable=AsyncMock, return_value="2885",
        ):
            result = await router.execute(order)

        assert result.success
        assert order.security_id == "2885"


# ── get_orders ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetOrders:
    async def test_paper_mode_returns_paper_orders(self):
        paper = PaperEngine(
            initial_capital=1_000_000, slippage_pct=0.0, brokerage=0.0,
        )
        paper.update_quote(_quote("RELIANCE", 2500))
        paper.execute_order(_buy_order())

        router = OrderRouter(_config("paper"), paper)
        orders = await router.get_orders()
        assert len(orders) == 1
        assert orders[0].order_id.startswith("PAPER-")

    async def test_live_mode_returns_broker_orders(self):
        live = AsyncMock()
        live.get_orders = AsyncMock(return_value=[
            OrderResponse(order_id="ORD1", status="COMPLETE"),
            OrderResponse(order_id="ORD2", status="PENDING"),
        ])

        router = OrderRouter(
            _config("live"), PaperEngine(), live_client=live,
        )
        orders = await router.get_orders()
        assert len(orders) == 2
        live.get_orders.assert_called_once()


# ── Broker property ──────────────────────────────────────────────────────────


class TestBrokerProperty:
    def test_broker_property_returns_config_value(self):
        router = OrderRouter(_config("paper", "kite"), PaperEngine())
        assert router.broker == "kite"

    def test_broker_property_default(self):
        router = OrderRouter(_config("paper", "indstocks"), PaperEngine())
        assert router.broker == "indstocks"


# ── CLI _create_live_client factory ──────────────────────────────────────────


try:
    import typer  # noqa: F401
    _HAS_TYPER = True
except ImportError:
    _HAS_TYPER = False


@pytest.mark.skipif(not _HAS_TYPER, reason="typer not installed")
class TestCreateLiveClient:
    def test_creates_kite_client(self):
        from skopaq.cli.main import _create_live_client

        config = MagicMock()
        config.broker = "kite"
        config.kite_api_key = MagicMock()
        config.kite_api_key.get_secret_value.return_value = "test_api_key"

        from skopaq.broker.kite_client import KiteConnectClient
        client = _create_live_client(config)
        assert isinstance(client, KiteConnectClient)

    def test_creates_indstocks_client(self):
        from skopaq.cli.main import _create_live_client

        config = MagicMock()
        config.broker = "indstocks"
        config.indstocks_base_url = "https://api.indstocks.com"

        from skopaq.broker.client import INDstocksClient
        client = _create_live_client(config)
        assert isinstance(client, INDstocksClient)

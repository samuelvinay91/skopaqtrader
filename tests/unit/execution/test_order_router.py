"""Unit tests for OrderRouter — paper/live dispatch and security_id resolution."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from skopaq.broker.models import (
    ExecutionResult,
    OrderRequest,
    OrderResponse,
    Side,
    TradingSignal,
)
from skopaq.broker.paper_engine import PaperEngine
from skopaq.execution.order_router import OrderRouter


def _make_config(mode: str = "paper") -> MagicMock:
    cfg = MagicMock()
    cfg.trading_mode = mode
    cfg.broker = "indstocks"
    cfg.initial_paper_capital = 1_000_000.0
    return cfg


def _buy_order(symbol: str = "RELIANCE", security_id: str = "") -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        side=Side.BUY,
        quantity=Decimal("10"),
        price=1800.0,
        security_id=security_id,
    )


def _signal() -> TradingSignal:
    return TradingSignal(
        symbol="RELIANCE",
        action="BUY",
        confidence=72,
        entry_price=1800.0,
    )


class TestPaperRouting:
    """Paper mode routes everything to the paper engine."""

    def test_paper_mode_uses_paper_engine(self):
        config = _make_config("paper")
        paper = PaperEngine(initial_capital=1_000_000)
        router = OrderRouter(config, paper)
        assert router.mode == "paper"

    def test_paper_mode_ignores_live_client(self):
        config = _make_config("paper")
        paper = PaperEngine(initial_capital=1_000_000)
        live = MagicMock()
        router = OrderRouter(config, paper, live_client=live)
        # Even with live_client, paper mode should use paper engine
        assert router.mode == "paper"


class TestLiveRouting:
    """Live mode routes to INDstocks client."""

    @pytest.mark.asyncio
    async def test_live_fallback_when_no_client(self):
        """If live_client is None, falls back to paper."""
        config = _make_config("live")
        paper = PaperEngine(initial_capital=1_000_000)
        # Inject a quote so paper fill works
        from skopaq.broker.models import Quote
        paper.update_quote(Quote(symbol="RELIANCE", ltp=1800.0))

        router = OrderRouter(config, paper, live_client=None)
        result = await router.execute(_buy_order(), _signal())
        # Should succeed via paper fallback
        assert result.success
        assert result.mode == "paper"

    @pytest.mark.asyncio
    async def test_live_resolves_security_id(self):
        """Live mode should resolve security_id if empty."""
        config = _make_config("live")
        paper = PaperEngine(initial_capital=1_000_000)

        live = AsyncMock()
        live.place_order = AsyncMock(return_value=OrderResponse(
            order_id="ORD123", status="PENDING", message="OK",
        ))

        router = OrderRouter(config, paper, live_client=live)

        order = _buy_order(security_id="")  # Empty — needs resolution

        with patch(
            "skopaq.broker.scrip_resolver.resolve_security_id",
            new_callable=AsyncMock,
            return_value="10604",
        ) as mock_resolve:
            result = await router.execute(order, _signal())

            mock_resolve.assert_called_once_with(live, "RELIANCE", "NSE")
            assert order.security_id == "10604"
            assert result.success
            assert result.mode == "live"

    @pytest.mark.asyncio
    async def test_live_skips_resolve_if_security_id_set(self):
        """If security_id is already set, skip resolution."""
        config = _make_config("live")
        paper = PaperEngine(initial_capital=1_000_000)

        live = AsyncMock()
        live.place_order = AsyncMock(return_value=OrderResponse(
            order_id="ORD456", status="PENDING", message="OK",
        ))

        router = OrderRouter(config, paper, live_client=live)
        order = _buy_order(security_id="10604")

        with patch(
            "skopaq.broker.scrip_resolver.resolve_security_id",
            new_callable=AsyncMock,
        ) as mock_resolve:
            result = await router.execute(order, _signal())

            mock_resolve.assert_not_called()
            assert result.success

    @pytest.mark.asyncio
    async def test_live_broker_error_does_not_fallback(self):
        """Broker errors should NOT silently fall back to paper."""
        config = _make_config("live")
        paper = PaperEngine(initial_capital=1_000_000)

        live = AsyncMock()
        live.place_order = AsyncMock(
            side_effect=Exception("Connection refused"),
        )

        router = OrderRouter(config, paper, live_client=live)
        order = _buy_order(security_id="10604")

        result = await router.execute(order, _signal())
        assert not result.success
        assert result.mode == "live"
        assert "Broker error" in result.rejection_reason

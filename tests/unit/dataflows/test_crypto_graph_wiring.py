"""Tests for crypto-specific graph wiring — state fields, conditional logic, propagation."""

import pytest


class TestAgentStateFields:
    """Verify the 3 new crypto report fields exist in AgentState."""

    def test_state_has_onchain_report(self):
        from tradingagents.agents.utils.agent_states import AgentState
        assert "onchain_report" in AgentState.__annotations__

    def test_state_has_defi_report(self):
        from tradingagents.agents.utils.agent_states import AgentState
        assert "defi_report" in AgentState.__annotations__

    def test_state_has_funding_report(self):
        from tradingagents.agents.utils.agent_states import AgentState
        assert "funding_report" in AgentState.__annotations__


class TestPropagationInitialState:
    """Verify initial state includes empty crypto report fields."""

    def test_initial_state_has_crypto_fields(self):
        from tradingagents.graph.propagation import Propagator

        prop = Propagator()
        state = prop.create_initial_state(
            company_name="BTCUSDT",
            trade_date="2024-01-15",
        )

        assert state["onchain_report"] == ""
        assert state["defi_report"] == ""
        assert state["funding_report"] == ""


class TestConditionalLogicMethods:
    """Verify the 3 new should_continue_X methods exist on ConditionalLogic."""

    def test_has_onchain_method(self):
        from tradingagents.graph.conditional_logic import ConditionalLogic
        assert hasattr(ConditionalLogic, "should_continue_onchain")

    def test_has_defi_method(self):
        from tradingagents.graph.conditional_logic import ConditionalLogic
        assert hasattr(ConditionalLogic, "should_continue_defi")

    def test_has_funding_method(self):
        from tradingagents.graph.conditional_logic import ConditionalLogic
        assert hasattr(ConditionalLogic, "should_continue_funding")


class TestSkopaqWrapperAnalystSelection:
    """Verify Skopaq auto-selects crypto analysts when asset_class is crypto."""

    def _make_wrapper(self, asset_class="equity", selected_analysts=None):
        """Create a SkopaqTradingGraph with minimal deps (no graph init)."""
        from unittest.mock import MagicMock
        from skopaq.graph.skopaq_graph import SkopaqTradingGraph

        executor = MagicMock()
        config = {"asset_class": asset_class}
        return SkopaqTradingGraph(
            upstream_config=config,
            executor=executor,
            selected_analysts=selected_analysts,
        )

    def test_equity_gets_4_base_analysts(self):
        wrapper = self._make_wrapper(asset_class="equity")
        assert wrapper._selected_analysts == ["market", "social", "news", "fundamentals"]

    def test_crypto_gets_7_analysts(self):
        wrapper = self._make_wrapper(asset_class="crypto")
        assert len(wrapper._selected_analysts) == 7
        assert "onchain" in wrapper._selected_analysts
        assert "defi" in wrapper._selected_analysts
        assert "funding" in wrapper._selected_analysts

    def test_explicit_override_respected(self):
        wrapper = self._make_wrapper(
            asset_class="crypto",
            selected_analysts=["market", "news"],
        )
        assert wrapper._selected_analysts == ["market", "news"]

    def test_no_asset_class_defaults_to_base(self):
        from unittest.mock import MagicMock
        from skopaq.graph.skopaq_graph import SkopaqTradingGraph

        wrapper = SkopaqTradingGraph(
            upstream_config={},
            executor=MagicMock(),
        )
        assert wrapper._selected_analysts == ["market", "social", "news", "fundamentals"]

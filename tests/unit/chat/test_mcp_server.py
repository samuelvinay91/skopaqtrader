"""Tests for the MCP server tool registration."""

from __future__ import annotations


def test_mcp_server_imports():
    from skopaq.mcp_server import mcp

    assert mcp is not None
    assert mcp._tool_manager is not None


def test_mcp_server_has_all_tools():
    from skopaq.mcp_server import mcp

    tool_names = {t.name for t in mcp._tool_manager._tools.values()}
    expected = {
        "get_quote",
        "get_historical",
        "get_positions",
        "get_holdings",
        "get_funds",
        "get_orders",
        "analyze_stock",
        "scan_market",
        "check_safety",
        "system_status",
        "place_order",
        "gather_market_data",
        "gather_news_data",
        "gather_fundamentals_data",
        "gather_social_data",
        "recall_agent_memories",
        "gather_all_analysis_data",
        "save_trade_reflection",
        "get_option_chain",
        "suggest_option_trade",
        "place_gtt_order",
        "list_gtt_orders",
        "setup_swing_trade",
    }
    assert tool_names == expected


def test_mcp_server_name():
    from skopaq.mcp_server import mcp

    assert mcp.name == "SkopaqTrader"


def test_mcp_server_has_instructions():
    from skopaq.mcp_server import mcp

    assert "trading" in mcp.instructions.lower()

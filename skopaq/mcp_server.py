"""MCP Server for SkopaqTrader — exposes broker and analysis tools.

Run as a standalone MCP server via stdio transport::

    python -m skopaq.mcp_server

Or add to Claude Desktop / Claude Code config::

    {
      "mcpServers": {
        "skopaq": {
          "command": "python3",
          "args": ["-m", "skopaq.mcp_server"]
        }
      }
    }

Any MCP-compatible client (Claude Desktop, Cursor, Windsurf) will
automatically discover these tools and make them available to the AI.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from mcp.server import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="SkopaqTrader",
    instructions=(
        "SkopaqTrader MCP server for Indian equity and crypto trading. "
        "Provides real-time quotes, historical data, portfolio management, "
        "AI-powered stock analysis, market scanning, and trade execution. "
        "Paper trading mode is the default — safe for experimentation."
    ),
)

# ── Lazy infrastructure ──────────────────────────────────────────────────────
# Built on first tool call to avoid import-time overhead.

_infra_cache: dict = {}


def _get_config():
    if "config" not in _infra_cache:
        from skopaq.config import SkopaqConfig
        from skopaq.llm import bridge_env_vars

        config = SkopaqConfig()
        bridge_env_vars(config)
        _infra_cache["config"] = config
    return _infra_cache["config"]


def _get_router():
    if "router" not in _infra_cache:
        from skopaq.broker.paper_engine import PaperEngine
        from skopaq.execution.order_router import OrderRouter

        config = _get_config()
        paper = PaperEngine(initial_capital=config.initial_paper_capital)
        router = OrderRouter(config, paper)
        _infra_cache["router"] = router
        _infra_cache["paper"] = paper
    return _infra_cache["router"]


# ── Market Data Tools ────────────────────────────────────────────────────────


@mcp.tool()
async def get_quote(symbol: str) -> str:
    """Get a real-time market quote for a stock symbol.

    Returns LTP, OHLC, bid/ask, volume, and change %.

    Args:
        symbol: Stock symbol (e.g. RELIANCE, TCS, INFY).
    """
    config = _get_config()

    from skopaq.broker.client import INDstocksClient
    from skopaq.broker.scrip_resolver import resolve_scrip_code
    from skopaq.broker.token_manager import TokenManager

    token_mgr = TokenManager()
    async with INDstocksClient(config, token_mgr) as client:
        scrip_code = await resolve_scrip_code(client, symbol)
        q = await client.get_quote(scrip_code, symbol=symbol)

    return json.dumps({
        "symbol": q.symbol,
        "exchange": q.exchange,
        "ltp": q.ltp,
        "open": q.open,
        "high": q.high,
        "low": q.low,
        "close": q.close,
        "bid": q.bid,
        "ask": q.ask,
        "volume": q.volume,
        "change_pct": q.change_pct,
    })


@mcp.tool()
async def get_historical(
    symbol: str,
    days: int = 5,
    resolution: int = 1,
) -> str:
    """Fetch historical OHLCV candles for a symbol.

    Args:
        symbol: Stock symbol (e.g. RELIANCE).
        days: Number of days of history (default 5).
        resolution: Candle resolution in minutes (1, 5, 15, 60).
    """
    config = _get_config()

    from skopaq.broker.client import INDstocksClient
    from skopaq.broker.scrip_resolver import resolve_scrip_code
    from skopaq.broker.token_manager import TokenManager

    now = datetime.now(timezone.utc)
    from_ts = int((now.timestamp() - days * 86400) * 1000)
    to_ts = int(now.timestamp() * 1000)

    # Map numeric resolution to INDstocks interval string
    interval_map = {1: "1minute", 5: "5minute", 15: "15minute", 30: "30minute", 60: "60minute"}
    interval = interval_map.get(resolution, f"{resolution}minute")

    token_mgr = TokenManager()
    async with INDstocksClient(config, token_mgr) as client:
        scrip_code = await resolve_scrip_code(client, symbol)
        candles = await client.get_historical(
            scrip_code, interval=interval, start_time=from_ts, end_time=to_ts,
        )

    return json.dumps({
        "symbol": symbol,
        "count": len(candles),
        "resolution_min": resolution,
        "candles": [
            {"ts": c.timestamp.isoformat(), "o": c.open, "h": c.high,
             "l": c.low, "c": c.close, "v": c.volume}
            for c in candles[-20:]  # Last 20 candles
        ],
    })


# ── Portfolio Tools ──────────────────────────────────────────────────────────


@mcp.tool()
async def get_positions() -> str:
    """Get open positions with P&L."""
    router = _get_router()
    positions = await router.get_positions()
    return json.dumps([
        {
            "symbol": p.symbol,
            "exchange": p.exchange,
            "quantity": str(p.quantity),
            "avg_price": p.average_price,
            "ltp": p.last_price,
            "pnl": p.pnl,
        }
        for p in positions
    ])


@mcp.tool()
async def get_holdings() -> str:
    """Get delivery holdings."""
    router = _get_router()
    holdings = await router.get_holdings()
    return json.dumps([
        {
            "symbol": h.symbol,
            "quantity": str(h.quantity),
            "avg_price": h.average_price,
            "ltp": h.last_price,
            "pnl": h.pnl,
        }
        for h in holdings
    ])


@mcp.tool()
async def get_funds() -> str:
    """Get available cash, margin, and collateral."""
    router = _get_router()
    funds = await router.get_funds()
    return json.dumps({
        "available_cash": funds.available_cash,
        "used_margin": funds.used_margin,
        "available_margin": funds.available_margin,
        "total_collateral": funds.total_collateral,
    })


@mcp.tool()
async def get_orders() -> str:
    """Get today's orders with status."""
    router = _get_router()
    orders = await router.get_orders()
    return json.dumps([
        {"order_id": o.order_id, "status": o.status, "message": o.message}
        for o in orders
    ])


# ── Analysis Tools ───────────────────────────────────────────────────────────


@mcp.tool()
async def analyze_stock(symbol: str, date: str = "") -> str:
    """Run full multi-agent AI analysis on a stock symbol.

    Returns BUY/SELL/HOLD recommendation with confidence, entry/stop/target
    prices, and reasoning. Takes 2-5 minutes.

    Args:
        symbol: Stock symbol (e.g. RELIANCE, TCS).
        date: Trade date YYYY-MM-DD (defaults to today).
    """
    config = _get_config()

    from skopaq.broker.paper_engine import PaperEngine
    from skopaq.execution.executor import Executor
    from skopaq.execution.order_router import OrderRouter
    from skopaq.execution.safety_checker import SafetyChecker
    from skopaq.graph.skopaq_graph import SkopaqTradingGraph
    from skopaq.llm import build_llm_map

    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    paper = PaperEngine(initial_capital=config.initial_paper_capital)
    router = OrderRouter(config, paper)
    safety = SafetyChecker(
        max_sector_concentration_pct=config.max_sector_concentration_pct
    )
    executor = Executor(router, safety)

    llm_map = build_llm_map()
    upstream = {
        "llm_provider": "google",
        "deep_think_llm": "gemini-3-flash-preview",
        "quick_think_llm": "gemini-3-flash-preview",
        "llm_map": llm_map,
        "max_debate_rounds": config.max_debate_rounds,
        "max_risk_discuss_rounds": config.max_risk_discuss_rounds,
        "asset_class": config.asset_class,
    }

    analysts = [a.strip() for a in config.selected_analysts.split(",") if a.strip()]
    graph = SkopaqTradingGraph(upstream, executor, selected_analysts=analysts)
    result = await graph.analyze(symbol, date)

    if result.error:
        return json.dumps({"error": result.error})

    signal = result.signal
    output = {
        "symbol": symbol,
        "date": date,
        "duration_seconds": result.duration_seconds,
    }
    if signal:
        output.update({
            "action": signal.action,
            "confidence": signal.confidence,
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "target": signal.target,
            "reasoning": signal.reasoning[:500] if signal.reasoning else "",
        })
    else:
        output["raw_decision"] = result.raw_decision[:500]

    return json.dumps(output)


@mcp.tool()
async def scan_market(max_candidates: int = 5) -> str:
    """Scan the market for top trading candidates using multi-model AI.

    Args:
        max_candidates: Maximum candidates to return (default 5).
    """
    config = _get_config()

    from langchain_core.messages import HumanMessage

    from skopaq.llm import build_llm_map, extract_text
    from skopaq.scanner import ScannerEngine, Watchlist

    llm_map = build_llm_map()
    watchlist = Watchlist()

    async def quote_fetcher(symbols):
        from skopaq.broker.client import INDstocksClient
        from skopaq.broker.scrip_resolver import resolve_scrip_code
        from skopaq.broker.token_manager import TokenManager

        token_mgr = TokenManager()
        async with INDstocksClient(config, token_mgr) as client:
            resolved = []
            for sym in symbols:
                try:
                    code = await resolve_scrip_code(client, sym)
                    resolved.append((sym, code))
                except ValueError:
                    pass
            if not resolved:
                return []
            syms, codes = zip(*resolved)
            raw = await client.get_quotes(list(codes), symbols=list(syms))
            return [
                {"symbol": q.symbol, "ltp": q.ltp, "open": q.open,
                 "high": q.high, "low": q.low, "close": q.close, "volume": q.volume}
                for q in raw
            ]

    async def _invoke(role, prompt):
        llm = llm_map.get(role, llm_map.get("_default"))
        if not llm:
            return "[]"
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        return extract_text(resp.content)

    scanner = ScannerEngine(
        watchlist=watchlist,
        max_candidates=max_candidates,
        quote_fetcher=quote_fetcher,
        llm_screener=lambda p: _invoke("market_analyst", p),
        news_screener=lambda p: _invoke("news_analyst", p),
        social_screener=lambda p: _invoke("social_analyst", p),
    )
    candidates = await scanner.scan_once()

    return json.dumps([
        {"symbol": c.symbol, "score": c.score, "reason": c.reason, "screener": c.screener}
        for c in candidates
    ])


@mcp.tool()
async def check_safety(
    symbol: str,
    quantity: int = 1,
    price: float = 0,
    side: str = "BUY",
) -> str:
    """Validate a hypothetical order against safety rules.

    Returns pass/fail with rejection reasons.

    Args:
        symbol: Stock symbol.
        quantity: Number of shares.
        price: Order price in INR.
        side: BUY or SELL.
    """
    from decimal import Decimal

    from skopaq.broker.models import OrderRequest, Side, TradingSignal

    router = _get_router()

    from skopaq.constants import PAPER_SAFETY_RULES
    from skopaq.execution.safety_checker import SafetyChecker

    safety = SafetyChecker(rules=PAPER_SAFETY_RULES)

    order = OrderRequest(
        symbol=symbol,
        side=Side(side.upper()),
        quantity=Decimal(str(quantity)),
        price=price if price else None,
    )
    signal = TradingSignal(
        symbol=symbol, action=side.upper(), confidence=50,
        entry_price=price if price else None, reasoning="Safety check",
    )
    positions = await router.get_positions()
    funds = await router.get_funds()

    result = safety.validate(
        order, signal, positions, funds,
        funds.available_cash + funds.used_margin,
    )

    return json.dumps({
        "passed": result.passed,
        "rejections": result.rejections,
    })


# ── System Tools ─────────────────────────────────────────────────────────────


@mcp.tool()
async def system_status() -> str:
    """Check SkopaqTrader system health: version, mode, token status, LLMs."""
    from skopaq import __version__
    from skopaq.broker.token_manager import TokenManager

    config = _get_config()
    health = TokenManager().get_health()

    llms = []
    for name, key_attr in [
        ("Gemini", "google_api_key"), ("Claude", "anthropic_api_key"),
        ("Perplexity", "perplexity_api_key"), ("Grok", "xai_api_key"),
    ]:
        if getattr(config, key_attr).get_secret_value():
            llms.append(name)

    return json.dumps({
        "version": __version__,
        "mode": config.trading_mode,
        "asset_class": config.asset_class,
        "token_valid": health.valid,
        "llms": llms,
        "paper_capital": config.initial_paper_capital,
    })


# ── Order Execution ──────────────────────────────────────────────────────────


@mcp.tool()
async def place_order(
    symbol: str,
    side: str = "BUY",
    quantity: int = 1,
    price: float = 0,
    order_type: str = "MARKET",
) -> str:
    """Place a paper or live order through the safety checker and order router.

    Paper mode is the default. Live mode requires explicit config change.
    All orders pass through the SafetyChecker before execution.

    Args:
        symbol: Stock symbol (e.g. RELIANCE).
        side: BUY or SELL.
        quantity: Number of shares.
        price: Limit price (0 = market order).
        order_type: MARKET or LIMIT.
    """
    from decimal import Decimal

    from skopaq.broker.models import (
        OrderRequest,
        OrderType,
        Side,
        TradingSignal,
    )
    from skopaq.constants import PAPER_SAFETY_RULES, SAFETY_RULES
    from skopaq.execution.safety_checker import SafetyChecker

    config = _get_config()
    router = _get_router()

    rules = PAPER_SAFETY_RULES if config.trading_mode == "paper" else SAFETY_RULES
    safety = SafetyChecker(
        rules=rules,
        max_sector_concentration_pct=config.max_sector_concentration_pct,
    )

    # Inject a quote for paper fill simulation
    if config.trading_mode == "paper" and price > 0:
        from skopaq.broker.models import Quote

        _infra_cache["paper"].update_quote(
            Quote(symbol=symbol, ltp=price, open=price, high=price,
                  low=price, close=price, bid=price, ask=price)
        )

    order = OrderRequest(
        symbol=symbol,
        side=Side(side.upper()),
        quantity=Decimal(str(quantity)),
        price=price if price > 0 else None,
        order_type=OrderType(order_type.upper()),
    )
    signal = TradingSignal(
        symbol=symbol,
        action=side.upper(),
        confidence=70,
        entry_price=price if price > 0 else None,
        quantity=Decimal(str(quantity)),
        reasoning="Placed via Claude Code MCP",
    )

    # Safety check first
    positions = await router.get_positions()
    funds = await router.get_funds()
    safety_result = safety.validate(
        order, signal, positions, funds,
        funds.available_cash + funds.used_margin,
    )

    if not safety_result.passed:
        return json.dumps({
            "success": False,
            "reason": f"Safety check failed: {safety_result.reason}",
        })

    # Execute
    result = await router.execute(order, signal)

    return json.dumps({
        "success": result.success,
        "mode": result.mode,
        "fill_price": result.fill_price,
        "slippage": result.slippage,
        "rejection_reason": result.rejection_reason or "",
    })


# ── Data Gathering Tools (for Claude-native analysis) ────────────────────────
# These tools fetch raw data that the multi-agent pipeline analysts need.
# Claude Code reasons with this data directly — no separate LLM calls.


def _setup_dataflow_config():
    """Ensure the upstream dataflow config is set for route_to_vendor."""
    from tradingagents.dataflows.config import get_config, set_config

    config = _get_config()
    is_crypto = config.asset_class == "crypto"
    upstream = {
        "data_vendors": {
            "core_stock_apis": "yfinance" if is_crypto else "indstocks",
            "technical_indicators": "yfinance",
            "fundamental_data": "yfinance",
            "news_data": "yfinance",
        },
        "yfinance_symbol_suffix": "" if is_crypto else ".NS",
    }
    set_config(upstream)
    return upstream


@mcp.tool()
async def gather_market_data(symbol: str, date: str = "") -> str:
    """Gather OHLCV price data and all key technical indicators for a symbol.

    Returns stock data + RSI, MACD, Bollinger Bands, SMA, EMA, ATR, VWMA.
    This is the data the Market Analyst uses for technical analysis.

    Args:
        symbol: Stock symbol (e.g. RELIANCE, TCS).
        date: Trading date YYYY-MM-DD (defaults to today).
    """
    import asyncio

    from tradingagents.dataflows.interface import route_to_vendor

    _setup_dataflow_config()

    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    start_date = (
        datetime.now(timezone.utc) - __import__("datetime").timedelta(days=60)
    ).strftime("%Y-%m-%d")

    # Fetch OHLCV data
    try:
        ohlcv = await asyncio.to_thread(
            route_to_vendor, "get_stock_data", symbol, start_date, date
        )
    except Exception as e:
        ohlcv = f"Error fetching stock data: {e}"

    # Fetch all standard indicators
    indicators = {}
    indicator_names = [
        "rsi", "macd", "macds", "macdh",
        "boll", "boll_ub", "boll_lb", "atr",
        "close_50_sma", "close_200_sma", "close_10_ema", "vwma",
    ]
    for ind in indicator_names:
        try:
            val = await asyncio.to_thread(
                route_to_vendor, "get_indicators", symbol, ind, date, 30
            )
            indicators[ind] = val
        except Exception as e:
            indicators[ind] = f"Error: {e}"

    return json.dumps({
        "symbol": symbol,
        "date": date,
        "ohlcv": ohlcv[:3000] if isinstance(ohlcv, str) else str(ohlcv)[:3000],
        "indicators": indicators,
    })


@mcp.tool()
async def gather_news_data(symbol: str, date: str = "") -> str:
    """Gather company-specific news and global macroeconomic news.

    Returns news articles from the past 7 days. This is the data the
    News Analyst and Social Analyst use.

    Args:
        symbol: Stock symbol (e.g. RELIANCE, TCS).
        date: Trading date YYYY-MM-DD (defaults to today).
    """
    import asyncio

    from tradingagents.dataflows.interface import route_to_vendor

    _setup_dataflow_config()

    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    start_date = (
        datetime.now(timezone.utc) - __import__("datetime").timedelta(days=7)
    ).strftime("%Y-%m-%d")

    try:
        company_news = await asyncio.to_thread(
            route_to_vendor, "get_news", symbol, start_date, date
        )
    except Exception as e:
        company_news = f"Error: {e}"

    try:
        global_news = await asyncio.to_thread(
            route_to_vendor, "get_global_news", date, 7, 5
        )
    except Exception as e:
        global_news = f"Error: {e}"

    try:
        insider = await asyncio.to_thread(
            route_to_vendor, "get_insider_transactions", symbol
        )
    except Exception as e:
        insider = f"Error: {e}"

    return json.dumps({
        "symbol": symbol,
        "company_news": company_news[:3000] if isinstance(company_news, str) else str(company_news)[:3000],
        "global_news": global_news[:3000] if isinstance(global_news, str) else str(global_news)[:3000],
        "insider_transactions": insider[:2000] if isinstance(insider, str) else str(insider)[:2000],
    })


@mcp.tool()
async def gather_fundamentals_data(symbol: str, date: str = "") -> str:
    """Gather company profile, balance sheet, cash flow, and income statement.

    This is the data the Fundamentals Analyst uses for financial evaluation.

    Args:
        symbol: Stock symbol (e.g. RELIANCE, TCS).
        date: Trading date YYYY-MM-DD (defaults to today).
    """
    import asyncio

    from tradingagents.dataflows.interface import route_to_vendor

    _setup_dataflow_config()

    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    results = {}
    for method in ["get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement"]:
        try:
            if method == "get_fundamentals":
                val = await asyncio.to_thread(route_to_vendor, method, symbol, date)
            else:
                val = await asyncio.to_thread(route_to_vendor, method, symbol, "annual", date)
            results[method] = val[:3000] if isinstance(val, str) else str(val)[:3000]
        except Exception as e:
            results[method] = f"Error: {e}"

    return json.dumps({
        "symbol": symbol,
        "fundamentals": results.get("get_fundamentals", ""),
        "balance_sheet": results.get("get_balance_sheet", ""),
        "cash_flow": results.get("get_cashflow", ""),
        "income_statement": results.get("get_income_statement", ""),
    })


@mcp.tool()
async def gather_social_data(symbol: str, date: str = "") -> str:
    """Gather social media sentiment and company news for sentiment analysis.

    This is the data the Social Media Analyst uses.

    Args:
        symbol: Stock symbol (e.g. RELIANCE, TCS).
        date: Trading date YYYY-MM-DD (defaults to today).
    """
    import asyncio

    from tradingagents.dataflows.interface import route_to_vendor

    _setup_dataflow_config()

    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    start_date = (
        datetime.now(timezone.utc) - __import__("datetime").timedelta(days=7)
    ).strftime("%Y-%m-%d")

    try:
        social_news = await asyncio.to_thread(
            route_to_vendor, "get_news", symbol, start_date, date
        )
    except Exception as e:
        social_news = f"Error: {e}"

    return json.dumps({
        "symbol": symbol,
        "social_sentiment_news": social_news[:4000] if isinstance(social_news, str) else str(social_news)[:4000],
    })


@mcp.tool()
async def recall_agent_memories(situation_summary: str) -> str:
    """Retrieve past lessons from agent memories using BM25 similarity search.

    Returns matched recommendations for all 5 memory roles (bull, bear,
    trader, invest_judge, risk_manager). These are injected into each
    agent perspective during analysis to learn from past trades.

    Args:
        situation_summary: Description of current market situation
            (typically a summary of the analyst reports).
    """
    config = _get_config()

    if not config.supabase_url or not config.supabase_service_key.get_secret_value():
        return json.dumps({"memories": {}, "note": "Supabase not configured"})

    try:
        from tradingagents.agents.utils.memory import FinancialSituationMemory
        from skopaq.memory.store import MemoryStore, MEMORY_ROLES
        from supabase import create_client

        client = create_client(
            config.supabase_url,
            config.supabase_service_key.get_secret_value(),
        )
        store = MemoryStore(client, max_entries=config.reflection_max_memory_entries)

        # Create temporary memory objects and load from Supabase
        class _MemHolder:
            pass

        holder = _MemHolder()
        for role in MEMORY_ROLES:
            setattr(holder, role, FinancialSituationMemory(name=role))

        loaded = store.load(holder)

        # Query each memory role
        memories = {}
        for role in MEMORY_ROLES:
            mem = getattr(holder, role)
            matches = mem.get_memories(situation_summary, n_matches=2)
            if matches:
                memories[role] = [
                    {"recommendation": m.get("recommendation", ""), "score": m.get("score", 0)}
                    for m in matches
                ]

        return json.dumps({
            "memories": memories,
            "total_loaded": loaded,
        })

    except Exception as e:
        logger.warning("Memory recall failed: %s", e)
        return json.dumps({"memories": {}, "error": str(e)})


@mcp.tool()
async def gather_all_analysis_data(symbol: str, date: str = "") -> str:
    """One-shot data gathering for the full multi-agent analysis pipeline.

    Fetches market data, news, fundamentals, and social data in parallel,
    plus agent memories. Returns a complete data bundle. Takes 10-30 seconds.

    Args:
        symbol: Stock symbol (e.g. RELIANCE, TCS).
        date: Trading date YYYY-MM-DD (defaults to today).
    """
    import asyncio

    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Fetch all data in parallel
    market_task = gather_market_data(symbol, date)
    news_task = gather_news_data(symbol, date)
    fundamentals_task = gather_fundamentals_data(symbol, date)
    social_task = gather_social_data(symbol, date)

    market, news, fundamentals, social = await asyncio.gather(
        market_task, news_task, fundamentals_task, social_task,
        return_exceptions=True,
    )

    # Convert exceptions to error strings
    for name, val in [("market", market), ("news", news), ("fundamentals", fundamentals), ("social", social)]:
        if isinstance(val, Exception):
            locals()[name] = json.dumps({"error": str(val)})

    # Retrieve agent memories using a brief summary
    summary = f"Analyzing {symbol} on {date}"
    try:
        memories = await recall_agent_memories(summary)
    except Exception:
        memories = json.dumps({"memories": {}})

    return json.dumps({
        "symbol": symbol,
        "date": date,
        "market_data": json.loads(market) if isinstance(market, str) else {"error": str(market)},
        "news_data": json.loads(news) if isinstance(news, str) else {"error": str(news)},
        "fundamentals_data": json.loads(fundamentals) if isinstance(fundamentals, str) else {"error": str(fundamentals)},
        "social_data": json.loads(social) if isinstance(social, str) else {"error": str(social)},
        "agent_memories": json.loads(memories) if isinstance(memories, str) else {"error": str(memories)},
    })


@mcp.tool()
async def save_trade_reflection(
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    pnl: float,
    pnl_pct: float,
    entry_reason: str = "",
    exit_reason: str = "",
) -> str:
    """Generate and store a post-trade reflection to update agent memory.

    This creates a lesson learned from the trade outcome so future
    analyses benefit from past experience.

    Args:
        symbol: Stock symbol.
        side: BUY or SELL.
        entry_price: Entry fill price.
        exit_price: Exit fill price.
        pnl: Realized P&L in INR.
        pnl_pct: P&L as percentage.
        entry_reason: Why the entry signal was generated.
        exit_reason: Why the position was closed.
    """
    config = _get_config()

    if not config.supabase_url or not config.supabase_service_key.get_secret_value():
        return json.dumps({"saved": False, "reason": "Supabase not configured"})

    try:
        from supabase import create_client
        from skopaq.memory.reflection import generate_reflection, store_reflection
        from skopaq.llm import build_llm_map

        llm_map = build_llm_map()
        llm = llm_map.get("sell_analyst", llm_map.get("_default"))

        reflection = await generate_reflection(
            llm,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            entry_reason=entry_reason,
            exit_reason=exit_reason,
        )

        client = create_client(
            config.supabase_url,
            config.supabase_service_key.get_secret_value(),
        )
        store_reflection(
            client,
            symbol=symbol,
            reflection=reflection,
            pnl=pnl,
            pnl_pct=pnl_pct,
        )

        return json.dumps({"saved": True, "reflection": reflection})

    except Exception as e:
        logger.warning("Reflection save failed: %s", e)
        return json.dumps({"saved": False, "error": str(e)})


# ── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")

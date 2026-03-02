"""Typer CLI for SkopaqTrader.

Usage examples::

    skopaq token set <token>          # Store INDstocks API token
    skopaq token status               # Check token health
    skopaq status                     # System health overview
    skopaq analyze RELIANCE           # Run agent analysis (no execution)
    skopaq trade RELIANCE             # Analyze + execute
    skopaq serve                      # Start FastAPI backend
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone

import typer

from skopaq import __version__
from skopaq.cli.display import (
    display_analyze_result,
    display_analyze_start,
    display_error,
    display_scan_results,
    display_scan_start,
    display_serve_banner,
    display_status,
    display_success,
    display_token_health,
    display_token_set,
    display_trade_result,
    display_trade_start,
    display_version,
    display_welcome,
)

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="skopaq",
    help="SkopaqTrader — India's first self-evolving AI trading platform.",
    no_args_is_help=True,
)

# ── Token management ─────────────────────────────────────────────────────────

token_app = typer.Typer(help="INDstocks API token management.")
app.add_typer(token_app, name="token")


@token_app.command("set")
def token_set(
    token: str = typer.Argument(..., help="Bearer token from INDstocks dashboard."),
    ttl: float = typer.Option(24.0, help="Token TTL in hours."),
) -> None:
    """Encrypt and store an INDstocks API token."""
    from skopaq.broker.token_manager import TokenManager

    mgr = TokenManager()
    mgr.set_token(token, ttl_hours=ttl)
    health = mgr.get_health()
    display_token_set(health)


@token_app.command("status")
def token_status() -> None:
    """Check current token health."""
    from skopaq.broker.token_manager import TokenManager

    mgr = TokenManager()
    health = mgr.get_health()
    display_token_health(health)

    if not health.valid:
        raise typer.Exit(code=1)


@token_app.command("clear")
def token_clear() -> None:
    """Delete stored token."""
    from skopaq.broker.token_manager import TokenManager

    mgr = TokenManager()
    mgr.clear()
    display_success("Token cleared")


# ── Status ───────────────────────────────────────────────────────────────────


@app.command("status")
def status() -> None:
    """Show system health overview."""
    from skopaq.broker.token_manager import TokenManager
    from skopaq.config import SkopaqConfig

    config = SkopaqConfig()
    mgr = TokenManager()
    health = mgr.get_health()

    # Detect configured LLMs
    llms = []
    if config.google_api_key.get_secret_value():
        llms.append("Gemini")
    if config.anthropic_api_key.get_secret_value():
        llms.append("Claude")
    if config.perplexity_api_key.get_secret_value():
        llms.append("Perplexity")
    if config.xai_api_key.get_secret_value():
        llms.append("Grok")
    if config.openrouter_api_key.get_secret_value():
        llms.append("OpenRouter")

    display_welcome()
    display_status(__version__, config, health, llms)


# ── Analyze ──────────────────────────────────────────────────────────────────


@app.command("analyze")
def analyze(
    symbol: str = typer.Argument(..., help="Stock symbol to analyze (e.g., RELIANCE)."),
    date: str = typer.Option("", help="Trade date (YYYY-MM-DD). Defaults to today."),
) -> None:
    """Run agent analysis for a symbol (no execution)."""
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    display_analyze_start(symbol, date)
    result = asyncio.run(_run_analyze(symbol, date))

    if result.error:
        display_error(result.error)
        raise typer.Exit(code=1)

    display_analyze_result(result)


async def _run_analyze(symbol: str, trade_date: str):
    """Helper to run async analysis."""
    from skopaq.broker.paper_engine import PaperEngine
    from skopaq.config import SkopaqConfig
    from skopaq.execution.executor import Executor
    from skopaq.execution.order_router import OrderRouter
    from skopaq.execution.safety_checker import SafetyChecker
    from skopaq.graph.skopaq_graph import SkopaqTradingGraph

    config = SkopaqConfig()
    paper = PaperEngine(initial_capital=config.initial_paper_capital)
    router = OrderRouter(config, paper)
    safety = SafetyChecker(
        max_sector_concentration_pct=config.max_sector_concentration_pct,
    )
    executor = Executor(router, safety)

    # Build upstream config (uses upstream defaults + our keys)
    upstream_config = _build_upstream_config(config)

    # Load persisted memories so agents have context from past trades
    memory_store = _create_memory_store(config)

    analysts = [a.strip() for a in config.selected_analysts.split(",") if a.strip()]
    graph = SkopaqTradingGraph(
        upstream_config, executor,
        selected_analysts=analysts,
        memory_store=memory_store,
    )
    return await graph.analyze(symbol, trade_date)


# ── Trade ────────────────────────────────────────────────────────────────────


@app.command("trade")
def trade(
    symbol: str = typer.Argument(..., help="Stock symbol to trade (e.g., RELIANCE)."),
    date: str = typer.Option("", help="Trade date (YYYY-MM-DD). Defaults to today."),
) -> None:
    """Analyze and execute a trade for a symbol."""
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    from skopaq.config import SkopaqConfig
    config = SkopaqConfig()

    display_trade_start(symbol, date, config.trading_mode)
    result = asyncio.run(_run_trade(symbol, date))

    if result.error:
        display_error(result.error)
        raise typer.Exit(code=1)

    display_trade_result(result)


async def _run_trade(symbol: str, trade_date: str):
    """Helper to run async trade.

    For paper mode, this function:
        1. Uses relaxed safety rules (no market-hours or stop-loss gate).
        2. Fetches a real-time quote from INDstocks and injects it into the
           paper engine so ``execute_order()`` can simulate a fill.
        3. Wires the trade lifecycle manager for auto-reflection on SELL.
    """
    from skopaq.broker.paper_engine import PaperEngine
    from skopaq.config import SkopaqConfig
    from skopaq.constants import PAPER_SAFETY_RULES, SAFETY_RULES
    from skopaq.execution.executor import Executor
    from skopaq.execution.order_router import OrderRouter
    from skopaq.execution.safety_checker import SafetyChecker
    from skopaq.graph.skopaq_graph import SkopaqTradingGraph

    from skopaq.risk.position_sizer import PositionSizer

    config = SkopaqConfig()
    paper = PaperEngine(initial_capital=config.initial_paper_capital)

    # Choose safety rules based on trading mode
    rules = PAPER_SAFETY_RULES if config.trading_mode == "paper" else SAFETY_RULES

    router = OrderRouter(config, paper)
    safety = SafetyChecker(
        rules=rules,
        max_sector_concentration_pct=config.max_sector_concentration_pct,
    )

    # ATR-based position sizer (optional)
    sizer = None
    if config.position_sizing_enabled:
        sizer = PositionSizer(
            risk_per_trade_pct=config.risk_per_trade_pct,
            atr_multiplier=config.atr_multiplier,
            atr_period=config.atr_period,
        )

    executor = Executor(router, safety, position_sizer=sizer)

    # For paper mode, fetch a real-time quote and inject into paper engine
    # so the fill simulation has a price to work with.
    if config.trading_mode == "paper":
        await _inject_paper_quote(config, paper, symbol)

    # Compute regime and calendar scales for position sizing
    regime_scale, calendar_scale = _compute_risk_scales(config, trade_date)

    upstream_config = _build_upstream_config(config)

    # Load persisted memories + wire lifecycle manager
    memory_store = _create_memory_store(config)
    analysts = [a.strip() for a in config.selected_analysts.split(",") if a.strip()]
    graph = SkopaqTradingGraph(
        upstream_config, executor,
        selected_analysts=analysts,
        memory_store=memory_store,
    )

    result = await graph.analyze_and_execute(
        symbol, trade_date,
        regime_scale=regime_scale,
        calendar_scale=calendar_scale,
    )

    # Post-execution: track lifecycle (BUY/SELL linkage + reflection)
    if config.reflection_enabled and memory_store is not None:
        await _run_lifecycle(config, graph, memory_store, result)

    return result


async def _inject_paper_quote(config, paper, symbol: str) -> None:
    """Fetch a real quote from INDstocks and inject it into the paper engine.

    The paper engine requires a Quote in its ``_quotes`` cache before
    ``execute_order()`` can simulate a fill.  Without this, it returns
    "No quote available for {symbol}".
    """
    from skopaq.broker.client import INDstocksClient
    from skopaq.broker.scrip_resolver import resolve_scrip_code
    from skopaq.broker.token_manager import TokenManager

    token_mgr = TokenManager()
    client = INDstocksClient(config, token_mgr)

    try:
        async with client:
            scrip_code = await resolve_scrip_code(client, symbol)
            logger.info("Resolved %s → %s", symbol, scrip_code)

            quote = await client.get_quote(scrip_code, symbol=symbol)
            paper.update_quote(quote)
            logger.info(
                "Injected quote: %s LTP=%.2f bid=%.2f ask=%.2f",
                symbol, quote.ltp, quote.bid, quote.ask,
            )
    except Exception as exc:
        logger.warning(
            "Could not fetch quote for %s — paper fill may fail: %s",
            symbol, exc,
        )


# ── Scan ──────────────────────────────────────────────────────────────────────


@app.command("scan")
def scan(
    max_candidates: int = typer.Option(5, help="Max candidates to return."),
) -> None:
    """Run a single scanner cycle on the NIFTY 50 watchlist."""
    display_scan_start()
    candidates = asyncio.run(_run_scan(max_candidates))
    display_scan_results(candidates)


async def _run_scan(max_candidates: int):
    """Helper to run async scanner."""
    from skopaq.config import SkopaqConfig
    from skopaq.scanner import ScannerEngine, Watchlist

    config = SkopaqConfig()
    scanner = ScannerEngine(
        watchlist=Watchlist(),
        max_candidates=max_candidates,
    )
    return await scanner.scan_once()


# ── Serve ────────────────────────────────────────────────────────────────────


@app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind address."),
    port: int = typer.Option(8000, help="Port."),
    reload: bool = typer.Option(False, help="Auto-reload on code changes."),
) -> None:
    """Start the FastAPI backend server."""
    import uvicorn

    display_serve_banner(host, port)
    uvicorn.run(
        "skopaq.api.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


# ── Version ──────────────────────────────────────────────────────────────────


@app.command("version")
def version() -> None:
    """Print version."""
    display_version(__version__)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _compute_risk_scales(config, trade_date: str) -> tuple[float, float]:
    """Compute regime and calendar position-sizing multipliers.

    Returns:
        (regime_scale, calendar_scale) — both default to 1.0 when disabled.
    """
    from datetime import date as date_cls

    regime_scale = 1.0
    calendar_scale = 1.0

    # Regime detection (India VIX + NIFTY trend)
    if config.regime_detection_enabled:
        try:
            from skopaq.risk.regime import RegimeDetector, fetch_regime_data

            india_vix, nifty_price, nifty_sma200 = fetch_regime_data()
            detector = RegimeDetector()
            regime = detector.detect(india_vix, nifty_price, nifty_sma200)
            regime_scale = regime.position_scale

            if not regime.should_trade:
                logger.warning(
                    "Regime detector says NO TRADE: %s VIX=%.1f",
                    regime.label, regime.vix or 0,
                )
        except Exception:
            logger.warning("Regime detection failed — using default scale", exc_info=True)

    # NSE Event Calendar
    try:
        from skopaq.risk.calendar import NSEEventCalendar

        cal = NSEEventCalendar()
        try:
            d = date_cls.fromisoformat(trade_date)
        except (ValueError, TypeError):
            d = date_cls.today()

        calendar_scale = cal.get_position_scale(d)
        events = cal.get_events(d)
        if events:
            logger.info("Calendar events for %s: %s (scale=%.1f)", d, events, calendar_scale)
    except Exception:
        logger.warning("Event calendar check failed — using default scale", exc_info=True)

    return regime_scale, calendar_scale


def _build_upstream_config(config) -> dict:
    """Build config dict for upstream TradingAgentsGraph from SkopaqConfig."""
    from pathlib import Path
    from skopaq.llm import bridge_env_vars, build_llm_map

    # Bridge SKOPAQ_ env vars → standard env vars (GOOGLE_API_KEY, etc.)
    bridge_env_vars(config)

    project_dir = str(Path.cwd())
    upstream = {
        "project_dir": project_dir,
        "results_dir": str(Path(project_dir) / "results"),
        "data_cache_dir": str(Path(project_dir) / ".cache" / "data"),
        "llm_provider": "google",  # Default to Gemini (cheapest)
        "deep_think_llm": "gemini-3-flash-preview",
        "quick_think_llm": "gemini-3-flash-preview",
        "backend_url": None,
        "max_debate_rounds": config.max_debate_rounds,
        "max_risk_discuss_rounds": config.max_risk_discuss_rounds,
        "google_thinking_level": config.google_thinking_level or None,
        "max_recur_limit": 100,
        # Indian market data vendor routing
        "data_vendors": {
            "core_stock_apis": "indstocks",       # INDstocks for OHLCV (native NSE)
            "technical_indicators": "yfinance",   # yfinance + .NS suffix
            "fundamental_data": "yfinance",       # yfinance + .NS suffix
            "news_data": "yfinance",              # yfinance + .NS suffix
        },
        "yfinance_symbol_suffix": ".NS",          # NSE suffix for yfinance calls
    }

    # Build per-role LLM map (multi-model tiering)
    try:
        upstream["llm_map"] = build_llm_map(upstream)
    except Exception:
        logger.warning("Failed to build LLM map — falling back to single-model", exc_info=True)

    return upstream


def _create_memory_store(config):
    """Create a MemoryStore if reflection is enabled and Supabase is configured.

    Returns None if either condition is not met (graceful degradation).
    """
    if not config.reflection_enabled:
        return None

    if not config.supabase_url or not config.supabase_service_key.get_secret_value():
        logger.debug("Supabase not configured — agent memory disabled")
        return None

    try:
        from supabase import create_client
        from skopaq.memory.store import MemoryStore

        client = create_client(
            config.supabase_url,
            config.supabase_service_key.get_secret_value(),
        )
        return MemoryStore(client, max_entries=config.reflection_max_memory_entries)
    except Exception:
        logger.warning("Failed to initialise MemoryStore — continuing without memory", exc_info=True)
        return None


async def _run_lifecycle(config, graph, memory_store, result):
    """Run trade lifecycle tracking (BUY/SELL linkage + auto-reflection).

    Silently does nothing if Supabase is not configured.
    """
    if not config.supabase_url or not config.supabase_service_key.get_secret_value():
        return

    try:
        from supabase import create_client
        from skopaq.db.repositories import TradeRepository
        from skopaq.memory.lifecycle import TradeLifecycleManager

        client = create_client(
            config.supabase_url,
            config.supabase_service_key.get_secret_value(),
        )
        trade_repo = TradeRepository(client)
        lifecycle = TradeLifecycleManager(trade_repo, graph, memory_store)
        await lifecycle.on_trade(result)
    except Exception:
        logger.warning("Trade lifecycle processing failed", exc_info=True)


def _setup_logging(level: str = "INFO") -> None:
    """Configure root logger."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


if __name__ == "__main__":
    _setup_logging()
    app()

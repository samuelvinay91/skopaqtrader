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
    display_daemon_report,
    display_daemon_start,
    display_error,
    display_monitor_ai_decision,
    display_monitor_result,
    display_monitor_start,
    display_monitor_tick,
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
    help="SkopaqTrader — AI algorithmic trading platform for Indian equities.",
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


# ── Kite Connect token management ────────────────────────────────────────────

kite_app = typer.Typer(help="Kite Connect (Zerodha) token management.")
app.add_typer(kite_app, name="kite")


@kite_app.command("login-url")
def kite_login_url() -> None:
    """Print the Kite Connect login URL."""
    from skopaq.broker.kite_token_manager import KiteTokenManager
    from skopaq.config import SkopaqConfig

    config = SkopaqConfig()
    api_key = config.kite_api_key.get_secret_value()
    if not api_key:
        display_error("SKOPAQ_KITE_API_KEY not set in .env")
        raise typer.Exit(code=1)

    url = KiteTokenManager.get_login_url(api_key)
    display_success(f"Open this URL in your browser:\n{url}")


@kite_app.command("set-token")
def kite_set_token(
    access_token: str = typer.Argument(..., help="Access token from Kite session."),
) -> None:
    """Store a Kite Connect access token."""
    from skopaq.broker.kite_token_manager import KiteTokenManager

    mgr = KiteTokenManager()
    mgr.set_token(access_token)
    health = mgr.get_health()
    if health.valid:
        display_success(
            f"Kite token stored. Expires at {health.expires_at}"
        )
    else:
        display_error(health.warning)


@kite_app.command("session")
def kite_session(
    request_token: str = typer.Argument(..., help="Request token from login redirect URL."),
) -> None:
    """Exchange request_token for access_token and store it."""
    from skopaq.broker.kite_token_manager import KiteTokenManager
    from skopaq.config import SkopaqConfig

    config = SkopaqConfig()
    api_key = config.kite_api_key.get_secret_value()
    api_secret = config.kite_api_secret.get_secret_value()

    if not api_key or not api_secret:
        display_error("SKOPAQ_KITE_API_KEY and SKOPAQ_KITE_API_SECRET must be set in .env")
        raise typer.Exit(code=1)

    mgr = KiteTokenManager()

    async def _generate():
        return await mgr.generate_session(api_key, api_secret, request_token)

    try:
        access_token = asyncio.run(_generate())
        display_success(f"Kite session established. Token: {access_token[:8]}...")
    except Exception as exc:
        display_error(f"Kite session failed: {exc}")
        raise typer.Exit(code=1)


@kite_app.command("status")
def kite_status() -> None:
    """Check Kite Connect token health."""
    from skopaq.broker.kite_token_manager import KiteTokenManager

    mgr = KiteTokenManager()
    health = mgr.get_health()
    if health.valid:
        display_success(
            f"Kite token valid. Expires in {health.remaining} (at {health.expires_at})"
        )
    else:
        display_error(health.warning)
        raise typer.Exit(code=1)


@kite_app.command("clear")
def kite_clear() -> None:
    """Delete stored Kite token."""
    from skopaq.broker.kite_token_manager import KiteTokenManager

    mgr = KiteTokenManager()
    mgr.clear()
    display_success("Kite token cleared")


# ── Status ───────────────────────────────────────────────────────────────────


@app.command("status")
def status() -> None:
    """Show system health overview."""
    from skopaq.config import SkopaqConfig

    config = SkopaqConfig()

    # Get token health for the configured broker
    if config.broker == "kite":
        from skopaq.broker.kite_token_manager import KiteTokenManager
        mgr = KiteTokenManager()
        health = mgr.get_health()
    else:
        from skopaq.broker.token_manager import TokenManager
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

    # For crypto, translate BTCUSDT → BTC-USD for yfinance-based analysis
    if config.asset_class == "crypto":
        from skopaq.broker.crypto_symbols import to_yfinance_ticker
        analysis_symbol = to_yfinance_ticker(symbol)
        logger.info("Crypto: %s → analysis as %s", symbol, analysis_symbol)
    else:
        analysis_symbol = symbol

    # Load persisted memories so agents have context from past trades
    memory_store = _create_memory_store(config)

    analysts = [a.strip() for a in config.selected_analysts.split(",") if a.strip()]
    graph = SkopaqTradingGraph(
        upstream_config, executor,
        selected_analysts=analysts,
        memory_store=memory_store,
    )
    return await graph.analyze(analysis_symbol, trade_date)


# ── Trade ────────────────────────────────────────────────────────────────────


@app.command("trade")
def trade(
    symbol: str = typer.Argument(None, help="Stock symbol (e.g., RELIANCE). Omit to auto-scan."),
    date: str = typer.Option("", help="Trade date (YYYY-MM-DD). Defaults to today."),
    top: int = typer.Option(1, "--top", help="Number of candidates to trade (when auto-scanning)."),
    watchlist: str = typer.Option("", "--watchlist", help="Comma-separated symbols to scan (instead of NIFTY 50)."),
    no_monitor: bool = typer.Option(False, "--no-monitor", help="Skip position monitoring after trade."),
) -> None:
    """Analyze and execute trades.

    With a symbol:   skopaq trade RELIANCE      (analyze + trade that symbol)
    Without symbol:  skopaq trade               (auto-scan → trade best pick)
    Multiple:        skopaq trade --top 3        (scan → trade top 3 candidates)
    Custom list:     skopaq trade --watchlist "RELIANCE,TCS,INFY"

    In paper mode, the full lifecycle runs automatically:
    scan → analyze → trade → monitor → close → report.
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    from skopaq.config import SkopaqConfig
    config = SkopaqConfig()

    # Double-confirmation gate for LIVE mode — real money at stake
    if config.trading_mode == "live":
        target = symbol or f"auto-scan (top {top})"
        typer.echo(
            f"\n  !!  LIVE TRADING MODE — real orders will be placed.\n"
            f"     Broker: {config.broker}\n"
            f"     Target: {target}    Date: {date}\n"
        )
        if not typer.confirm("  Proceed with LIVE execution?", default=False):
            typer.echo("  Aborted.")
            raise typer.Exit()

    if symbol:
        # Explicit symbol — single trade flow
        display_trade_start(symbol, date, config.trading_mode)
        result = asyncio.run(_run_trade_full(
            symbols=[symbol],
            trade_date=date,
            monitor=not no_monitor,
        ))
    else:
        # Auto-scan → trade top N candidates
        wl = [s.strip() for s in watchlist.split(",") if s.strip()] if watchlist else None
        typer.echo(
            f"\n  Auto-scan mode: finding top {top} candidate(s)"
            + (f" from {wl}" if wl else " from NIFTY 50")
            + f"  [{config.trading_mode}]\n"
        )
        result = asyncio.run(_run_trade_full(
            symbols=None,
            trade_date=date,
            max_candidates=top,
            custom_watchlist=wl,
            monitor=not no_monitor,
        ))

    # Display results
    if isinstance(result, dict) and "report" in result:
        display_daemon_report(result["report"])
    elif hasattr(result, "error") and result.error:
        display_error(result.error)
        raise typer.Exit(code=1)
    elif hasattr(result, "signal"):
        display_trade_result(result)


async def _run_trade(symbol: str, trade_date: str):
    """Helper to run async trade.

    For paper mode, this function:
        1. Uses relaxed safety rules (no market-hours or stop-loss gate).
        2. Fetches a real-time quote from INDstocks and injects it into the
           paper engine so ``execute_order()`` can simulate a fill.
        3. Wires the trade lifecycle manager for auto-reflection on SELL.
    """
    from skopaq.broker.market_data import MarketDataProvider
    from skopaq.broker.paper_engine import PaperEngine
    from skopaq.config import SkopaqConfig
    from skopaq.constants import (
        CRYPTO_PAPER_SAFETY_RULES, CRYPTO_SAFETY_RULES,
        PAPER_SAFETY_RULES, SAFETY_RULES,
    )
    from skopaq.execution.executor import Executor
    from skopaq.execution.order_router import OrderRouter
    from skopaq.execution.safety_checker import SafetyChecker
    from skopaq.graph.skopaq_graph import SkopaqTradingGraph

    from skopaq.risk.position_sizer import PositionSizer

    config = SkopaqConfig()
    is_crypto = config.asset_class == "crypto"

    # MarketDataProvider — auto-fallback: broker API → yfinance → cache
    market_data = MarketDataProvider(config)

    # Paper engine — crypto uses % brokerage + USDT capital
    if is_crypto:
        paper = PaperEngine(
            initial_capital=config.initial_paper_capital,
            brokerage_pct=0.001,         # 0.1% Binance spot fee
            currency_label="USDT",
            market_data=market_data,
        )
    else:
        paper = PaperEngine(
            initial_capital=config.initial_paper_capital,
            market_data=market_data,
        )

    # Choose safety rules based on trading mode + asset class
    if is_crypto:
        rules = CRYPTO_PAPER_SAFETY_RULES if config.trading_mode == "paper" else CRYPTO_SAFETY_RULES
    else:
        rules = PAPER_SAFETY_RULES if config.trading_mode == "paper" else SAFETY_RULES

    # Wire live broker client when in live mode; also attach to market data
    live_client = None
    if config.trading_mode == "live":
        live_client = _create_live_client(config)
    else:
        # In paper mode, try to attach a broker client for best-quality data.
        # If no token is available, MarketDataProvider falls back to yfinance.
        try:
            broker_client = _create_live_client(config)
            await broker_client.__aenter__()
            market_data.set_broker_client(broker_client)
            logger.info("Paper mode: attached %s broker for live market data", config.broker)
        except Exception:
            logger.info("Paper mode: no broker token — using yfinance for market data")

    router = OrderRouter(config, paper, live_client=live_client)
    safety = SafetyChecker(
        rules=rules,
        max_sector_concentration_pct=config.max_sector_concentration_pct,
    )

    # ATR-based position sizer (optional — also works for crypto via yfinance)
    sizer = None
    if config.position_sizing_enabled:
        sizer = PositionSizer(
            risk_per_trade_pct=config.risk_per_trade_pct,
            atr_multiplier=config.atr_multiplier,
            atr_period=config.atr_period,
        )

    executor = Executor(router, safety, position_sizer=sizer)

    # Compute regime and calendar scales for position sizing
    # (India VIX + NSE calendar are irrelevant for crypto — skip)
    if is_crypto:
        regime_scale, calendar_scale = 1.0, 1.0
    else:
        regime_scale, calendar_scale = _compute_risk_scales(config, trade_date)

    upstream_config = _build_upstream_config(config)

    # For crypto, translate BTCUSDT → BTC-USD for yfinance-based analysis
    if is_crypto:
        from skopaq.broker.crypto_symbols import to_yfinance_ticker
        analysis_symbol = to_yfinance_ticker(symbol)
        # Store the original Binance symbol for trade record building
        upstream_config["_trade_symbol"] = symbol
        logger.info("Crypto: %s → analysis as %s", symbol, analysis_symbol)
    else:
        analysis_symbol = symbol

    # Load persisted memories + wire lifecycle manager
    memory_store = _create_memory_store(config)
    analysts = [a.strip() for a in config.selected_analysts.split(",") if a.strip()]
    graph = SkopaqTradingGraph(
        upstream_config, executor,
        selected_analysts=analysts,
        memory_store=memory_store,
    )

    # Open live client context if wired (INDstocksClient requires async with)
    if live_client is not None:
        await live_client.__aenter__()

    try:
        result = await graph.analyze_and_execute(
            analysis_symbol, trade_date,
            regime_scale=regime_scale,
            calendar_scale=calendar_scale,
        )
    finally:
        if live_client is not None:
            await live_client.__aexit__(None, None, None)

    # Post-execution: track lifecycle (BUY/SELL linkage + reflection)
    if config.reflection_enabled and memory_store is not None:
        await _run_lifecycle(config, graph, memory_store, result)

    return result


async def _run_trade_full(
    symbols: list[str] | None,
    trade_date: str,
    max_candidates: int = 1,
    custom_watchlist: list[str] | None = None,
    monitor: bool = True,
) -> dict:
    """Full-lifecycle trade: scan → analyze → trade → monitor → close → report.

    When ``symbols`` is provided, skips the scanner and trades those symbols.
    When ``symbols`` is None, runs the scanner to discover candidates.

    In paper mode, the full cycle runs including position monitoring.
    In live mode, monitoring is optional (controlled by ``monitor`` flag).

    Returns a dict with ``{"report": DaemonSessionReport}`` for the CLI
    to display, or a single AnalysisResult if only one symbol was traded.
    """
    import signal as sig

    from skopaq.broker.market_data import MarketDataProvider
    from skopaq.broker.paper_engine import PaperEngine
    from skopaq.config import SkopaqConfig
    from skopaq.constants import (
        CRYPTO_PAPER_SAFETY_RULES, CRYPTO_SAFETY_RULES,
        PAPER_SAFETY_RULES, SAFETY_RULES,
    )
    from skopaq.execution.daemon import DaemonSessionReport
    from skopaq.execution.executor import Executor
    from skopaq.execution.order_router import OrderRouter
    from skopaq.execution.safety_checker import SafetyChecker
    from skopaq.graph.skopaq_graph import SkopaqTradingGraph
    from skopaq.risk.position_sizer import PositionSizer

    config = SkopaqConfig()
    is_crypto = config.asset_class == "crypto"
    is_paper = config.trading_mode == "paper"

    report = DaemonSessionReport(
        session_date=trade_date,
    )

    # ── 1. Market data + paper engine ────────────────────────────────
    market_data = MarketDataProvider(config)

    if is_crypto:
        paper = PaperEngine(
            initial_capital=config.initial_paper_capital,
            brokerage_pct=0.001,
            currency_label="USDT",
            market_data=market_data,
        )
    else:
        paper = PaperEngine(
            initial_capital=config.initial_paper_capital,
            market_data=market_data,
        )

    if is_crypto:
        rules = CRYPTO_PAPER_SAFETY_RULES if is_paper else CRYPTO_SAFETY_RULES
    else:
        rules = PAPER_SAFETY_RULES if is_paper else SAFETY_RULES

    # ── 2. Broker client ────────────────────────────────────────────
    live_client = None
    broker_client = None
    if config.trading_mode == "live":
        live_client = _create_live_client(config)
        broker_client = live_client
    else:
        try:
            broker_client = _create_live_client(config)
        except Exception:
            logger.info("No broker token — using yfinance for market data")

    router = OrderRouter(config, paper, live_client=live_client)
    safety = SafetyChecker(
        rules=rules,
        max_sector_concentration_pct=config.max_sector_concentration_pct,
    )
    sizer = None
    if config.position_sizing_enabled:
        sizer = PositionSizer(
            risk_per_trade_pct=config.risk_per_trade_pct,
            atr_multiplier=config.atr_multiplier,
            atr_period=config.atr_period,
        )
    executor = Executor(router, safety, position_sizer=sizer)

    # Open broker context
    if broker_client is not None:
        try:
            await broker_client.__aenter__()
            market_data.set_broker_client(broker_client)
        except Exception:
            logger.info("Broker client open failed — using yfinance fallback")
            broker_client = None

    # ── 3. Discover symbols (scan if needed) ─────────────────────────
    try:
        if symbols:
            trade_symbols = symbols
            logger.info("Explicit symbols: %s", trade_symbols)
        else:
            logger.info("Running scanner to find top %d candidate(s)...", max_candidates)
            try:
                candidates = await _run_scan(
                    max_candidates,
                )
                report.candidates_scanned = len(candidates)
                trade_symbols = [c.symbol for c in candidates[:max_candidates]]
                logger.info(
                    "Scanner found %d candidates: %s",
                    len(trade_symbols), trade_symbols,
                )
                if not trade_symbols:
                    logger.info("No candidates found — nothing to trade")
                    return {"report": report}
            except Exception as exc:
                logger.error("Scanner failed: %s", exc, exc_info=True)
                report.errors.append(f"Scanner error: {exc}")
                return {"report": report}

        # ── 4. Analyze + trade each symbol ───────────────────────────
        upstream_config = _build_upstream_config(config)
        memory_store = _create_memory_store(config)
        analysts = [a.strip() for a in config.selected_analysts.split(",") if a.strip()]
        graph = SkopaqTradingGraph(
            upstream_config, executor,
            selected_analysts=analysts,
            memory_store=memory_store,
        )

        regime_scale, calendar_scale = (
            (1.0, 1.0) if is_crypto
            else _compute_risk_scales(config, trade_date)
        )

        buys_placed = 0
        for sym in trade_symbols:
            report.candidates_analyzed += 1
            logger.info("Analyzing %s...", sym)

            # Pre-warm quote cache
            try:
                await market_data.get_quote(sym)
            except Exception:
                logger.debug("Quote pre-warm failed for %s", sym)

            try:
                result = await graph.analyze_and_execute(
                    sym, trade_date,
                    regime_scale=regime_scale,
                    calendar_scale=calendar_scale,
                )
            except Exception as exc:
                logger.error("Analysis failed for %s: %s", sym, exc, exc_info=True)
                report.errors.append(f"{sym}: {exc}")
                continue

            if result.error:
                report.errors.append(f"{sym}: {result.error}")
                continue

            if result.signal is None or result.signal.action == "HOLD":
                report.holds += 1
                logger.info("[%s] Decision: HOLD", sym)
                continue

            if result.signal.action == "BUY":
                if result.execution and result.execution.success:
                    buys_placed += 1
                    report.trades_opened += 1
                    logger.info(
                        "[%s] BUY EXECUTED — fill=%.2f qty=%s",
                        sym,
                        result.execution.fill_price or 0,
                        result.signal.quantity,
                    )

                    # Reflection
                    if config.reflection_enabled and memory_store:
                        try:
                            await _run_lifecycle(config, graph, memory_store, result)
                        except Exception:
                            logger.debug("Lifecycle failed for %s", sym, exc_info=True)
                else:
                    report.trades_rejected += 1
                    reason = (
                        result.execution.rejection_reason
                        if result.execution else "no execution result"
                    )
                    logger.warning("[%s] BUY REJECTED: %s", sym, reason)

            # For single-symbol non-monitored mode, return the raw result
            if len(trade_symbols) == 1 and not monitor:
                return result

        # ── 5. Monitor positions ─────────────────────────────────────
        if monitor and buys_placed > 0:
            from skopaq.execution.position_monitor import PositionMonitor

            logger.info(
                "Starting position monitor (%d position(s))...",
                buys_placed,
            )

            stop_event = asyncio.Event()

            def _handle_sigint(*_):
                logger.info("Ctrl+C — shutting down monitor...")
                stop_event.set()

            loop = asyncio.get_running_loop()
            try:
                loop.add_signal_handler(sig.SIGINT, _handle_sigint)
            except NotImplementedError:
                pass  # Windows

            # Build LLM for sell analyst
            llm = None
            try:
                from skopaq.llm import bridge_env_vars, build_llm_map
                bridge_env_vars(config)
                llm_map = build_llm_map()
                llm = llm_map.get("sell_analyst", llm_map.get("_default"))
            except Exception:
                logger.debug("No LLM for sell analyst — rule-based only")

            mon = PositionMonitor(
                executor=executor,
                market_data=market_data,
                router=router,
                config=config,
                llm=llm,
                stop_event=stop_event,
                ai_enabled=llm is not None,
            )
            monitor_result = await mon.run()
            report.monitor_result = monitor_result
            report.sells_executed = monitor_result.sells_executed
            report.sells_failed = monitor_result.sells_failed
            report.gross_pnl = monitor_result.total_pnl
        elif buys_placed == 0:
            logger.info("No positions opened — skipping monitor")

        # ── 6. Close remaining positions ─────────────────────────────
        if buys_placed > 0:
            try:
                positions = await router.get_positions()
                open_pos = [p for p in positions if p.quantity > 0]
                if open_pos:
                    from decimal import Decimal
                    from skopaq.broker.models import TradingSignal

                    logger.info("Closing %d remaining position(s)...", len(open_pos))
                    for pos in open_pos:
                        try:
                            signal = TradingSignal(
                                symbol=pos.symbol, action="SELL",
                                confidence=100,
                                entry_price=pos.average_price,
                                quantity=Decimal(int(pos.quantity)),
                                reasoning="Session close: auto-sell remaining positions",
                            )
                            sell_result = await executor.execute_signal(signal)
                            if sell_result.success:
                                logger.info("Closed %s", pos.symbol)
                            else:
                                logger.warning(
                                    "Close rejected for %s: %s",
                                    pos.symbol, sell_result.rejection_reason,
                                )
                        except Exception:
                            logger.error("Close failed for %s", pos.symbol, exc_info=True)
            except Exception:
                logger.debug("Position check failed during close", exc_info=True)

    finally:
        # Clean up broker session
        if broker_client is not None:
            try:
                await broker_client.__aexit__(None, None, None)
            except Exception:
                pass

    return {"report": report}


def _create_live_client(config):
    """Create the appropriate live broker client based on config.broker.

    Returns an INDstocksClient or KiteConnectClient (both are async context managers).
    """
    if config.broker == "kite":
        from skopaq.broker.kite_client import KiteConnectClient
        from skopaq.broker.kite_token_manager import KiteTokenManager

        token_mgr = KiteTokenManager()
        return KiteConnectClient(config, token_mgr)
    else:
        from skopaq.broker.client import INDstocksClient
        from skopaq.broker.token_manager import TokenManager

        token_mgr = TokenManager()
        return INDstocksClient(config, token_mgr)


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
    """Helper to run async scanner with real providers.

    Wires up:
    - quote_fetcher:  INDstocks batch quotes (equity) or stub (crypto)
    - llm_screener:   Gemini 3 Flash  (technical screening)
    - news_screener:  Perplexity Sonar (news-aware screening)
    - social_screener: Grok            (social sentiment screening)
    """
    from langchain_core.messages import HumanMessage

    from skopaq.config import SkopaqConfig
    from skopaq.llm import bridge_env_vars, build_llm_map, extract_text
    from skopaq.scanner import ScannerEngine, Watchlist

    config = SkopaqConfig()

    # Bridge SKOPAQ_ env vars → standard env vars
    bridge_env_vars(config)

    # Build per-role LLM map
    llm_map = build_llm_map()

    # Activate semantic cache (saves $$)
    from skopaq.llm.cache import init_langcache
    cache = init_langcache(config)
    if cache:
        from langchain_core.globals import set_llm_cache
        set_llm_cache(cache)
        logger.info("Scanner: semantic cache enabled")

    # ── Quote fetcher ────────────────────────────────────────────────
    is_crypto = config.asset_class == "crypto"

    if is_crypto:
        from skopaq.broker.crypto_symbols import CRYPTO_TOP_20
        watchlist = Watchlist(symbols=CRYPTO_TOP_20)

        async def quote_fetcher(symbols: list[str]) -> list[dict]:
            """Crypto stub — no real-time quotes wired yet."""
            return []
    else:
        watchlist = Watchlist()

        if config.broker == "kite":
            async def quote_fetcher(symbols: list[str]) -> list[dict]:
                """Batch-fetch Kite Connect quotes for equity symbols."""
                from skopaq.broker.kite_client import KiteConnectClient
                from skopaq.broker.kite_token_manager import KiteTokenManager

                token_mgr = KiteTokenManager()
                async with KiteConnectClient(config, token_mgr) as client:
                    kite_keys = [f"NSE:{sym}" for sym in symbols]
                    raw_quotes = await client.get_quotes(kite_keys, symbols=symbols)

                    return [
                        {
                            "symbol": q.symbol,
                            "ltp": q.ltp,
                            "open": q.open,
                            "high": q.high,
                            "low": q.low,
                            "close": q.close,
                            "volume": q.volume,
                        }
                        for q in raw_quotes
                    ]
        else:
            async def quote_fetcher(symbols: list[str]) -> list[dict]:
                """Batch-fetch INDstocks quotes for equity symbols."""
                from skopaq.broker.client import INDstocksClient
                from skopaq.broker.scrip_resolver import resolve_scrip_code
                from skopaq.broker.token_manager import TokenManager

                token_mgr = TokenManager()
                async with INDstocksClient(config, token_mgr) as client:
                    # Resolve all symbols → scrip codes (instruments CSV cached 1h)
                    resolved: list[tuple[str, str]] = []
                    for sym in symbols:
                        try:
                            code = await resolve_scrip_code(client, sym)
                            resolved.append((sym, code))
                        except ValueError:
                            logger.debug("Scrip resolve failed: %s", sym)

                    if not resolved:
                        return []

                    syms, codes = zip(*resolved)
                    raw_quotes = await client.get_quotes(list(codes), symbols=list(syms))

                    return [
                        {
                            "symbol": q.symbol,
                            "ltp": q.ltp,
                            "open": q.open,
                            "high": q.high,
                            "low": q.low,
                            "close": q.close,
                            "volume": q.volume,
                        }
                        for q in raw_quotes
                    ]

    # ── LLM screener factories ───────────────────────────────────────

    async def _invoke_llm(role: str, prompt: str) -> str:
        """Invoke a LangChain LLM by role and return normalised text."""
        llm = llm_map.get(role, llm_map.get("_default"))
        if llm is None:
            return "[]"
        msg = HumanMessage(content=prompt)
        if hasattr(llm, "ainvoke"):
            response = await llm.ainvoke([msg])
        else:
            import asyncio as _aio
            response = await _aio.to_thread(lambda: llm.invoke([msg]))
        return extract_text(response.content)

    async def llm_screener(prompt: str) -> str:
        return await _invoke_llm("market_analyst", prompt)

    async def news_screener(prompt: str) -> str:
        return await _invoke_llm("news_analyst", prompt)

    async def social_screener(prompt: str) -> str:
        return await _invoke_llm("social_analyst", prompt)

    # ── Run scanner ──────────────────────────────────────────────────
    scanner = ScannerEngine(
        watchlist=watchlist,
        max_candidates=max_candidates,
        quote_fetcher=quote_fetcher,
        llm_screener=llm_screener,
        news_screener=news_screener,
        social_screener=social_screener,
    )
    return await scanner.scan_once()


# ── Monitor ─────────────────────────────────────────────────────────────────


@app.command("monitor")
def monitor(
    poll_interval: int = typer.Option(0, help="Poll interval in seconds (0 = use config)."),
    stop_loss: float = typer.Option(0.0, help="Hard stop-loss % override (0 = use config)."),
    eod_exit_minutes: int = typer.Option(0, help="EOD exit minutes override (0 = use config)."),
    no_ai: bool = typer.Option(False, "--no-ai", help="Disable AI sell analyst (rule-based only)."),
) -> None:
    """Monitor open positions and auto-sell using AI + safety rules."""
    from skopaq.config import SkopaqConfig

    config = SkopaqConfig()

    # Apply CLI overrides
    if poll_interval > 0:
        config.monitor_poll_interval_seconds = poll_interval
    if stop_loss > 0:
        config.monitor_hard_stop_pct = stop_loss
    if eod_exit_minutes > 0:
        config.monitor_eod_exit_minutes_before_close = eod_exit_minutes

    ai_enabled = not no_ai

    display_monitor_start(
        mode=config.trading_mode,
        poll_interval=config.monitor_poll_interval_seconds,
        stop_pct=config.monitor_hard_stop_pct,
        eod_minutes=config.monitor_eod_exit_minutes_before_close,
        ai_enabled=ai_enabled,
    )

    result = asyncio.run(_run_monitor(config, ai_enabled))
    display_monitor_result(result)


async def _run_monitor(config, ai_enabled: bool):
    """Async helper to run the position monitor."""
    import signal as sig

    from skopaq.broker.market_data import MarketDataProvider
    from skopaq.constants import PAPER_SAFETY_RULES, SAFETY_RULES
    from skopaq.execution.executor import Executor
    from skopaq.execution.order_router import OrderRouter
    from skopaq.execution.position_monitor import PositionMonitor
    from skopaq.execution.safety_checker import SafetyChecker

    # MarketDataProvider — handles all LTP/quote fetching for any broker
    market_data = MarketDataProvider(config)

    # Wire live or paper backend
    from skopaq.broker.paper_engine import PaperEngine

    paper = PaperEngine(
        initial_capital=config.initial_paper_capital,
        market_data=market_data,
    )
    live_client = None
    broker_client = None

    if config.trading_mode == "live":
        live_client = _create_live_client(config)
        broker_client = live_client
    else:
        # Paper mode — try to attach broker for real market data
        try:
            broker_client = _create_live_client(config)
        except Exception:
            logger.info("No broker token — using yfinance for market data")

    router = OrderRouter(config, paper, live_client=live_client)
    rules = PAPER_SAFETY_RULES if config.trading_mode == "paper" else SAFETY_RULES
    safety = SafetyChecker(
        rules=rules,
        max_sector_concentration_pct=config.max_sector_concentration_pct,
    )
    executor = Executor(router, safety)

    # Build LLM for sell analyst (if AI enabled)
    llm = None
    if ai_enabled:
        try:
            from skopaq.llm import bridge_env_vars, build_llm_map

            bridge_env_vars(config)
            llm_map = build_llm_map()
            llm = llm_map.get("sell_analyst", llm_map.get("_default"))
            if llm:
                logger.info("Sell analyst LLM ready")
            else:
                logger.warning("No LLM available for sell_analyst — AI tier disabled")
                ai_enabled = False
        except Exception:
            logger.warning("Failed to build LLM map — AI tier disabled", exc_info=True)
            ai_enabled = False

    # Graceful shutdown via Ctrl+C
    stop_event = asyncio.Event()

    def _handle_sigint(*_):
        logger.info("Ctrl+C received — shutting down monitor gracefully...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(sig.SIGINT, _handle_sigint)

    # Open broker client context and wire into market data provider
    if broker_client is not None:
        await broker_client.__aenter__()
        market_data.set_broker_client(broker_client)

    try:
        monitor_instance = PositionMonitor(
            executor=executor,
            market_data=market_data,
            router=router,
            config=config,
            llm=llm,
            stop_event=stop_event,
            ai_enabled=ai_enabled,
        )
        return await monitor_instance.run()
    finally:
        if broker_client is not None:
            await broker_client.__aexit__(None, None, None)


# ── Daemon ───────────────────────────────────────────────────────────────────


@app.command("daemon")
def daemon(
    max_trades: int = typer.Option(0, help="Override max trades per session (0 = use config)."),
    paper: bool = typer.Option(False, "--paper", help="Force paper mode."),
    live: bool = typer.Option(False, "--live", help="Force live mode (real orders on INDstocks)."),
    once: bool = typer.Option(False, "--once", help="Run immediately without waiting for market open."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Scanner only — print candidates, don't trade."),
    confirm_live: bool = typer.Option(False, "--confirm-live", help="Skip interactive confirmation for live mode (for cron/CI)."),
) -> None:
    """Run the autonomous trading daemon (scan -> trade -> monitor -> close)."""
    from skopaq.config import SkopaqConfig

    config = SkopaqConfig()

    # CLI overrides
    if paper:
        config.trading_mode = "paper"
    if live:
        config.trading_mode = "live"
    if max_trades > 0:
        config.daemon_max_trades_per_session = max_trades

    # Double-confirmation gate for LIVE mode — real money at stake
    if config.trading_mode == "live" and not dry_run:
        typer.echo(
            "\n  !!  LIVE DAEMON MODE — autonomous trading with real money.\n"
            f"     Max trades: {config.daemon_max_trades_per_session}\n"
            f"     Min profit: {config.daemon_min_profit_threshold_pct}% / "
            f"{config.daemon_min_profit_threshold_inr:.0f}\n"
        )
        if not confirm_live:
            if not typer.confirm("  Proceed with LIVE daemon?", default=False):
                typer.echo("  Aborted.")
                raise typer.Exit()

    display_daemon_start(config)
    report = asyncio.run(_run_daemon(config, once=once, dry_run=dry_run))
    display_daemon_report(report)


async def _run_daemon(config, *, once: bool = False, dry_run: bool = False):
    """Async helper to run the daemon session."""
    import signal as sig

    from skopaq.execution.daemon import TradingDaemon

    stop_event = asyncio.Event()

    # Graceful shutdown on SIGINT/SIGTERM
    def _handle_signal(signum, *_):
        sig_name = sig.Signals(signum).name
        logger.info("%s received — initiating graceful shutdown...", sig_name)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for s in (sig.SIGINT, sig.SIGTERM):
        loop.add_signal_handler(s, _handle_signal, s)

    daemon_instance = TradingDaemon(config, stop_event=stop_event)

    # Wait for market open (unless --once or --dry-run)
    if not once and not dry_run:
        await daemon_instance.wait_for_market_open()

    if stop_event.is_set():
        from skopaq.execution.daemon import DaemonSessionReport
        return DaemonSessionReport(session_date="cancelled")

    return await daemon_instance.run_session(dry_run=dry_run)


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
    is_crypto = config.asset_class == "crypto"

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
        "asset_class": config.asset_class,
        # Data vendor routing — crypto uses yfinance everywhere (no INDstocks)
        "data_vendors": {
            "core_stock_apis": "yfinance" if is_crypto else "indstocks",
            "technical_indicators": "yfinance",
            "fundamental_data": "yfinance",
            "news_data": "yfinance",
        },
        # Crypto: no suffix (BTC-USD works as-is); Equity: .NS for NSE
        "yfinance_symbol_suffix": "" if is_crypto else ".NS",
    }

    # Build per-role LLM map (multi-model tiering)
    try:
        upstream["llm_map"] = build_llm_map(upstream)
    except Exception:
        logger.warning("Failed to build LLM map — falling back to single-model", exc_info=True)

    # Activate semantic LLM cache (Redis LangCache)
    from skopaq.llm.cache import init_langcache
    cache = init_langcache(config)
    if cache:
        from langchain_core.globals import set_llm_cache
        set_llm_cache(cache)
        logger.info(
            "Semantic cache enabled (threshold=%.2f)",
            config.langcache_threshold,
        )

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

    Flow:
        1. Persist the trade to Supabase (so find_open_buy() works for future SELLs)
        2. Run lifecycle manager (BUY/SELL linkage + reflection)

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

        # Step 1: Persist the trade BEFORE lifecycle processing.
        # This is the critical link — without it, find_open_buy() never finds
        # BUYs and the entire self-evolution loop is broken.
        trade_record = _build_trade_record(result, config)
        if trade_record is not None:
            try:
                saved = trade_repo.insert(trade_record)
                result.trade_id = saved.id
                logger.info(
                    "Trade persisted: %s %s id=%s (paper=%s)",
                    trade_record.side, trade_record.symbol,
                    saved.id, trade_record.is_paper,
                )
            except Exception:
                logger.warning(
                    "Failed to persist trade to Supabase — lifecycle will "
                    "continue but BUY/SELL linkage may not work",
                    exc_info=True,
                )

        # Step 2: Run lifecycle (BUY/SELL linkage + reflection)
        lifecycle = TradeLifecycleManager(trade_repo, graph, memory_store)
        await lifecycle.on_trade(result)
    except Exception:
        logger.warning("Trade lifecycle processing failed", exc_info=True)


def _build_trade_record(result, config):
    """Convert an AnalysisResult into a TradeRecord for Supabase persistence.

    Returns None if the result doesn't represent a successful execution
    (e.g., HOLD signals, failed orders, or analysis-only runs).
    """
    if result.signal is None:
        return None
    if result.execution is None or not result.execution.success:
        return None
    if result.signal.action == "HOLD":
        return None

    from decimal import Decimal
    from skopaq.db.models import TradeRecord

    # Build model_signals dict from cache/timing metadata
    model_signals = {}
    if result.cache_hits or result.cache_misses:
        model_signals["cache_hits"] = result.cache_hits
        model_signals["cache_misses"] = result.cache_misses
    if result.duration_seconds:
        model_signals["duration_seconds"] = result.duration_seconds

    # Determine exchange and product based on asset class
    is_crypto = config.asset_class == "crypto"
    trade_symbol = result.symbol
    if is_crypto:
        # result.symbol may be the yfinance format (BTC-USD); restore Binance pair
        from skopaq.broker.crypto_symbols import to_binance_pair
        trade_symbol = to_binance_pair(result.symbol, config.crypto_quote_currency)

    return TradeRecord(
        symbol=trade_symbol,
        exchange="BINANCE" if is_crypto else "NSE",
        product="SPOT" if is_crypto else "CNC",
        side=result.signal.action,
        quantity=result.signal.quantity or Decimal("1"),
        price=(
            Decimal(str(result.signal.entry_price))
            if result.signal.entry_price else None
        ),
        fill_price=(
            Decimal(str(result.execution.fill_price))
            if result.execution.fill_price else None
        ),
        slippage=(
            Decimal(str(result.execution.slippage))
            if result.execution.slippage else Decimal("0")
        ),
        brokerage=Decimal(str(result.execution.brokerage)),
        is_paper=(result.execution.mode == "paper"),
        status="COMPLETE",
        signal_source="skopaq-ai",
        consensus_score=result.signal.confidence,
        entry_reason=(
            result.signal.reasoning[:2000]
            if result.signal.reasoning else None
        ),
        agent_decision={
            "action": result.signal.action,
            "confidence": result.signal.confidence,
        },
        model_signals=model_signals,
    )


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

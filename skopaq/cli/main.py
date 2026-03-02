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
    typer.echo(f"Token stored. Expires at {health.expires_at} ({health.remaining} remaining)")


@token_app.command("status")
def token_status() -> None:
    """Check current token health."""
    from skopaq.broker.token_manager import TokenManager

    mgr = TokenManager()
    health = mgr.get_health()

    if health.valid:
        typer.echo(f"Token: VALID")
        typer.echo(f"Expires: {health.expires_at}")
        typer.echo(f"Remaining: {health.remaining}")
        if health.warning:
            typer.secho(f"Warning: {health.warning}", fg=typer.colors.YELLOW)
    else:
        typer.secho(f"Token: INVALID — {health.warning}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@token_app.command("clear")
def token_clear() -> None:
    """Delete stored token."""
    from skopaq.broker.token_manager import TokenManager

    mgr = TokenManager()
    mgr.clear()
    typer.echo("Token cleared.")


# ── Status ───────────────────────────────────────────────────────────────────


@app.command("status")
def status() -> None:
    """Show system health overview."""
    from skopaq.broker.token_manager import TokenManager
    from skopaq.config import SkopaqConfig

    config = SkopaqConfig()
    mgr = TokenManager()
    health = mgr.get_health()

    typer.echo(f"SkopaqTrader v{__version__}")
    typer.echo(f"─────────────────────────────")
    typer.echo(f"Mode:      {config.trading_mode.upper()}")
    typer.echo(f"Broker:    INDstocks ({config.indstocks_base_url})")

    # Token
    if health.valid:
        typer.echo(f"Token:     VALID ({health.remaining} remaining)")
    else:
        typer.secho(f"Token:     INVALID — {health.warning}", fg=typer.colors.RED)

    # Supabase
    if config.supabase_url:
        typer.echo(f"Supabase:  configured")
    else:
        typer.secho(f"Supabase:  NOT configured", fg=typer.colors.YELLOW)

    # LLMs
    llms = []
    if config.google_api_key.get_secret_value():
        llms.append("Gemini")
    if config.anthropic_api_key.get_secret_value():
        llms.append("Claude")
    if config.perplexity_api_key.get_secret_value():
        llms.append("Perplexity")
    if config.xai_api_key.get_secret_value():
        llms.append("Grok")
    typer.echo(f"LLMs:      {', '.join(llms) if llms else 'NONE configured'}")

    # Redis
    if config.upstash_redis_url:
        typer.echo(f"Redis:     configured (Upstash)")
    else:
        typer.secho(f"Redis:     NOT configured", fg=typer.colors.YELLOW)


# ── Analyze ──────────────────────────────────────────────────────────────────


@app.command("analyze")
def analyze(
    symbol: str = typer.Argument(..., help="Stock symbol to analyze (e.g., RELIANCE)."),
    date: str = typer.Option("", help="Trade date (YYYY-MM-DD). Defaults to today."),
) -> None:
    """Run agent analysis for a symbol (no execution)."""
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    typer.echo(f"Analyzing {symbol} for {date}...")
    result = asyncio.run(_run_analyze(symbol, date))

    if result.error:
        typer.secho(f"Error: {result.error}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if result.signal:
        typer.echo(f"Signal: {result.signal.action} (confidence={result.signal.confidence}%)")
        if result.signal.entry_price:
            typer.echo(f"Entry:  {result.signal.entry_price}")
        if result.signal.stop_loss:
            typer.echo(f"SL:     {result.signal.stop_loss}")
        if result.signal.target:
            typer.echo(f"Target: {result.signal.target}")
        typer.echo(f"Reason: {result.signal.reasoning[:200]}")
    else:
        typer.echo("No signal generated.")

    typer.echo(f"Duration: {result.duration_seconds}s")


async def _run_analyze(symbol: str, trade_date: str):
    """Helper to run async analysis."""
    from skopaq.config import SkopaqConfig
    from skopaq.graph.skopaq_graph import SkopaqTradingGraph
    from skopaq.execution.executor import Executor
    from skopaq.execution.order_router import OrderRouter
    from skopaq.execution.safety_checker import SafetyChecker
    from skopaq.broker.paper_engine import PaperEngine

    config = SkopaqConfig()
    paper = PaperEngine(initial_capital=config.initial_paper_capital)
    router = OrderRouter(config, paper)
    safety = SafetyChecker()
    executor = Executor(router, safety)

    # Build upstream config (uses upstream defaults + our keys)
    upstream_config = _build_upstream_config(config)

    graph = SkopaqTradingGraph(upstream_config, executor)
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
    typer.echo(f"Trading {symbol} for {date} (mode={config.trading_mode})...")

    result = asyncio.run(_run_trade(symbol, date))

    if result.error:
        typer.secho(f"Error: {result.error}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if result.signal:
        typer.echo(f"Signal: {result.signal.action} (confidence={result.signal.confidence}%)")

    if result.execution:
        ex = result.execution
        if ex.success:
            typer.secho(
                f"Executed: {ex.mode} fill @ {ex.fill_price} "
                f"(slippage={ex.slippage}, brokerage={ex.brokerage})",
                fg=typer.colors.GREEN,
            )
        else:
            typer.secho(f"Rejected: {ex.rejection_reason}", fg=typer.colors.RED)
    else:
        typer.echo("No execution (HOLD or no signal).")

    typer.echo(f"Duration: {result.duration_seconds}s")


async def _run_trade(symbol: str, trade_date: str):
    """Helper to run async trade."""
    from skopaq.config import SkopaqConfig
    from skopaq.graph.skopaq_graph import SkopaqTradingGraph
    from skopaq.execution.executor import Executor
    from skopaq.execution.order_router import OrderRouter
    from skopaq.execution.safety_checker import SafetyChecker
    from skopaq.broker.paper_engine import PaperEngine

    config = SkopaqConfig()
    paper = PaperEngine(initial_capital=config.initial_paper_capital)
    router = OrderRouter(config, paper)
    safety = SafetyChecker()
    executor = Executor(router, safety)

    upstream_config = _build_upstream_config(config)
    graph = SkopaqTradingGraph(upstream_config, executor)
    return await graph.analyze_and_execute(symbol, trade_date)


# ── Scan ──────────────────────────────────────────────────────────────────────


@app.command("scan")
def scan(
    max_candidates: int = typer.Option(5, help="Max candidates to return."),
) -> None:
    """Run a single scanner cycle on the NIFTY 50 watchlist."""
    typer.echo("Running scanner cycle...")
    candidates = asyncio.run(_run_scan(max_candidates))

    if not candidates:
        typer.echo("No candidates found.")
        return

    for c in candidates:
        urgency_marker = " [HIGH]" if c.urgency == "high" else ""
        typer.echo(f"  {c.symbol}{urgency_marker}: {c.reason}")

    typer.echo(f"\n{len(candidates)} candidate(s) found.")


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

    typer.echo(f"Starting SkopaqTrader API on {host}:{port}")
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
    typer.echo(f"SkopaqTrader v{__version__}")


# ── Helpers ──────────────────────────────────────────────────────────────────


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
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "max_recur_limit": 100,
    }

    # Build per-role LLM map (multi-model tiering)
    try:
        upstream["llm_map"] = build_llm_map(upstream)
    except Exception:
        logger.warning("Failed to build LLM map — falling back to single-model", exc_info=True)

    return upstream


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

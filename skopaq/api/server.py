"""FastAPI backend for SkopaqTrader.

Provides REST endpoints for the frontend dashboard and health checks.
Deployed on Railway via ``skopaq serve``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from skopaq import __version__
from skopaq.broker.token_manager import TokenManager
from skopaq.config import SkopaqConfig

logger = logging.getLogger(__name__)

app = FastAPI(
    title="SkopaqTrader API",
    version=__version__,
    docs_url="/docs",
)

# CORS — allow frontend (Vercel) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    """Health check endpoint (used by Railway)."""
    config = SkopaqConfig()
    token_mgr = TokenManager()
    health = token_mgr.get_health()

    return {
        "status": "ok",
        "version": __version__,
        "mode": config.trading_mode,
        "token_valid": health.valid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/status")
async def system_status() -> dict:
    """Detailed system status for the dashboard."""
    config = SkopaqConfig()
    token_mgr = TokenManager()
    token_health = token_mgr.get_health()

    return {
        "version": __version__,
        "mode": config.trading_mode,
        "broker": {
            "name": "INDstocks",
            "base_url": config.indstocks_base_url,
            "token_valid": token_health.valid,
            "token_expires_at": token_health.expires_at.isoformat() if token_health.expires_at else None,
            "token_remaining": str(token_health.remaining) if token_health.remaining else None,
            "token_warning": token_health.warning or None,
        },
        "services": {
            "supabase": bool(config.supabase_url),
            "redis": bool(config.upstash_redis_url),
            "llms": {
                "gemini": bool(config.google_api_key.get_secret_value()),
                "claude": bool(config.anthropic_api_key.get_secret_value()),
                "perplexity": bool(config.perplexity_api_key.get_secret_value()),
                "grok": bool(config.xai_api_key.get_secret_value()),
            },
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Scanner ───────────────────────────────────────────────────────────────────

_scanner_engine = None


def _get_scanner():
    """Lazy-init scanner engine singleton."""
    global _scanner_engine
    if _scanner_engine is None:
        from skopaq.scanner import ScannerEngine, Watchlist
        config = SkopaqConfig()
        _scanner_engine = ScannerEngine(
            watchlist=Watchlist(),
            cycle_seconds=config.scanner_cycle_seconds,
            max_candidates=config.scanner_max_candidates,
        )
    return _scanner_engine


@app.on_event("startup")
async def _start_scanner():
    """Start scanner as a background task if enabled in config."""
    config = SkopaqConfig()
    if config.scanner_enabled:
        scanner = _get_scanner()
        await scanner.start()
        logger.info("Scanner background task started")


@app.on_event("shutdown")
async def _stop_scanner():
    """Stop scanner on shutdown."""
    if _scanner_engine and _scanner_engine.running:
        await _scanner_engine.stop()


@app.get("/api/scanner/status")
async def scanner_status() -> dict:
    """Scanner engine status."""
    scanner = _get_scanner()
    return scanner.status


@app.get("/api/scanner/candidates")
async def scanner_candidates() -> dict:
    """Recent scanner candidates."""
    scanner = _get_scanner()
    candidates = []
    # Drain the queue (non-blocking)
    while not scanner.candidate_queue.empty():
        try:
            c = scanner.candidate_queue.get_nowait()
            candidates.append(c.to_dict())
        except Exception:
            break
    return {
        "candidates": candidates,
        "last_candidates": [c.to_dict() for c in scanner._last_candidates],
    }


@app.get("/api/portfolio")
async def portfolio() -> dict:
    """Current portfolio snapshot (paper mode)."""
    from skopaq.broker.paper_engine import PaperEngine

    config = SkopaqConfig()
    paper = PaperEngine(initial_capital=config.initial_paper_capital)
    snapshot = paper.get_snapshot()

    return {
        "total_value": float(snapshot.total_value),
        "cash": float(snapshot.cash),
        "positions_value": float(snapshot.positions_value),
        "day_pnl": float(snapshot.day_pnl),
        "positions": [p.model_dump() for p in snapshot.positions],
        "open_orders": snapshot.open_orders,
        "mode": config.trading_mode,
        "timestamp": snapshot.timestamp.isoformat(),
    }

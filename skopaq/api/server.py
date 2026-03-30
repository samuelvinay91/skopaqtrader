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
from skopaq.config import SkopaqConfig

logger = logging.getLogger(__name__)


app = FastAPI(
    title="SkopaqTrader API",
    description="AI algorithmic trading platform for Indian equities.",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_token_health(config: SkopaqConfig):
    """Get token health for the configured broker."""
    if config.broker == "kite":
        from skopaq.broker.kite_token_manager import KiteTokenManager
        return KiteTokenManager().get_health()
    else:
        from skopaq.broker.token_manager import TokenManager
        return TokenManager().get_health()


# ── Health Check ─────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    """Lightweight health check for Railway / load balancers."""
    config = SkopaqConfig()
    health = _get_token_health(config)

    return {
        "status": "ok",
        "version": __version__,
        "mode": config.trading_mode,
        "broker": config.broker,
        "product": config.default_product,
        "token_valid": health.valid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/status")
async def system_status() -> dict:
    """Detailed system status for the dashboard."""
    config = SkopaqConfig()
    token_health = _get_token_health(config)

    return {
        "version": __version__,
        "mode": config.trading_mode,
        "product": config.default_product,
        "broker": {
            "name": config.broker,
            "token_valid": token_health.valid,
            "token_expires_at": (
                token_health.expires_at.isoformat() if token_health.expires_at else None
            ),
            "token_remaining": (
                str(token_health.remaining) if token_health.remaining else None
            ),
            "token_warning": token_health.warning or None,
        },
        "market_data": {
            "angelone": bool(config.angelone_api_key.get_secret_value()),
            "upstox": bool(config.upstox_access_token.get_secret_value()),
            "yfinance": True,  # Always available
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


@app.post("/api/scan")
async def run_scan(max_candidates: int = 5) -> dict:
    """Run a single scanner cycle and return candidates."""
    try:
        from skopaq.cli.main import _run_scan

        candidates = await _run_scan(max_candidates)
        return {
            "candidates": [c.to_dict() for c in candidates] if candidates else [],
        }
    except Exception as exc:
        logger.error("Scanner failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Portfolio ─────────────────────────────────────────────────────────────────


@app.get("/api/portfolio")
async def portfolio() -> dict:
    """Current portfolio snapshot (paper mode)."""
    from skopaq.broker.market_data import MarketDataProvider
    from skopaq.broker.paper_engine import PaperEngine

    config = SkopaqConfig()
    market_data = MarketDataProvider(config)
    paper = PaperEngine(
        initial_capital=config.initial_paper_capital,
        market_data=market_data,
    )
    snapshot = paper.get_snapshot()

    return {
        "total_value": float(snapshot.total_value),
        "cash": float(snapshot.cash),
        "positions_value": float(snapshot.positions_value),
        "day_pnl": float(snapshot.day_pnl),
        "positions": [p.model_dump() for p in snapshot.positions],
        "open_orders": snapshot.open_orders,
        "mode": config.trading_mode,
        "product": config.default_product,
        "timestamp": snapshot.timestamp.isoformat(),
    }

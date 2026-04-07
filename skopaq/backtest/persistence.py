"""Persist backtest, WFO, and Monte Carlo results to Fly.io Postgres.

Connects via DATABASE_URL environment variable (set by Fly.io attachment).
Falls back to local SQLite for development.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_engine = None


def _get_db_url() -> str:
    """Get database URL from env or config."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            from skopaq.config import SkopaqConfig
            url = SkopaqConfig().database_url
        except Exception:
            pass
    if not url:
        # Fallback to local SQLite
        url = "sqlite:///skopaq_backtest.db"
    return url


def _get_connection():
    """Get a database connection."""
    import psycopg2

    url = _get_db_url()
    if url.startswith("sqlite"):
        import sqlite3
        return sqlite3.connect(url.replace("sqlite:///", ""))

    return psycopg2.connect(url)


def save_backtest_result(
    symbol: str,
    strategy: str,
    start_date: str,
    end_date: str,
    total_return: float,
    annual_return: float,
    sharpe: float,
    sortino: float,
    calmar: float,
    max_drawdown: float,
    win_rate: float,
    profit_factor: float,
    total_trades: int,
    config: dict,
) -> int:
    """Save backtest result to database."""
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO backtest_results
            (symbol, strategy, start_date, end_date, total_return, annual_return,
             sharpe_ratio, sortino_ratio, calmar_ratio, max_drawdown,
             win_rate, profit_factor, total_trades, config)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id""",
            (symbol, strategy, start_date, end_date, total_return, annual_return,
             sharpe, sortino, calmar, max_drawdown, win_rate, profit_factor,
             total_trades, json.dumps(config)),
        )
        row_id = cur.fetchone()[0]
        conn.commit()
        conn.close()
        logger.info("Backtest saved: %s %s id=%d", symbol, strategy, row_id)
        return row_id
    except Exception as exc:
        logger.warning("Failed to save backtest: %s", exc)
        return 0


def save_wfo_result(
    symbol: str,
    total_periods: int,
    wfe_pct: float,
    avg_oos_return: float,
    avg_oos_sharpe: float,
    consistency_pct: float,
    periods: list,
) -> int:
    """Save walk-forward result to database."""
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO wfo_results
            (symbol, total_periods, wfe_pct, avg_oos_return, avg_oos_sharpe,
             consistency_pct, periods)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id""",
            (symbol, total_periods, wfe_pct, avg_oos_return, avg_oos_sharpe,
             consistency_pct, json.dumps(periods)),
        )
        row_id = cur.fetchone()[0]
        conn.commit()
        conn.close()
        logger.info("WFO saved: %s WFE=%.1f%% id=%d", symbol, wfe_pct, row_id)
        return row_id
    except Exception as exc:
        logger.warning("Failed to save WFO: %s", exc)
        return 0


def save_monte_carlo_result(
    symbol: str,
    n_simulations: int,
    median_return: float,
    p5_return: float,
    p95_return: float,
    worst_max_dd: float,
    median_sharpe: float,
    probability_of_loss: float,
    probability_of_ruin: float,
) -> int:
    """Save Monte Carlo result to database."""
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO monte_carlo_results
            (symbol, n_simulations, median_return, p5_return, p95_return,
             worst_max_dd, median_sharpe, probability_of_loss, probability_of_ruin)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id""",
            (symbol, n_simulations, median_return, p5_return, p95_return,
             worst_max_dd, median_sharpe, probability_of_loss, probability_of_ruin),
        )
        row_id = cur.fetchone()[0]
        conn.commit()
        conn.close()
        logger.info("Monte Carlo saved: %s id=%d", symbol, row_id)
        return row_id
    except Exception as exc:
        logger.warning("Failed to save Monte Carlo: %s", exc)
        return 0


def save_strategy_params(
    symbol: str,
    strategy: str,
    params: dict,
    performance: dict,
) -> int:
    """Save or update strategy parameters."""
    try:
        conn = _get_connection()
        cur = conn.cursor()

        # Deactivate old params for same symbol/strategy
        cur.execute(
            """UPDATE strategy_params SET is_active = false
            WHERE symbol = %s AND strategy = %s AND is_active = true""",
            (symbol, strategy),
        )

        # Insert new params
        cur.execute(
            """INSERT INTO strategy_params
            (symbol, strategy, params, performance, is_active)
            VALUES (%s, %s, %s, %s, true)
            RETURNING id""",
            (symbol, strategy, json.dumps(params), json.dumps(performance)),
        )
        row_id = cur.fetchone()[0]
        conn.commit()
        conn.close()
        logger.info("Strategy params saved: %s %s id=%d", symbol, strategy, row_id)
        return row_id
    except Exception as exc:
        logger.warning("Failed to save strategy params: %s", exc)
        return 0


def get_active_params(symbol: str, strategy: str) -> Optional[dict]:
    """Get current active strategy parameters."""
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            """SELECT params, performance FROM strategy_params
            WHERE symbol = %s AND strategy = %s AND is_active = true
            ORDER BY created_at DESC LIMIT 1""",
            (symbol, strategy),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return {"params": json.loads(row[0]), "performance": json.loads(row[1])}
        return None
    except Exception as exc:
        logger.warning("Failed to get params: %s", exc)
        return None


def get_backtest_history(symbol: str, limit: int = 10) -> list[dict]:
    """Get recent backtest results for a symbol."""
    try:
        conn = _get_connection()
        cur = conn.cursor()
        cur.execute(
            """SELECT strategy, start_date, end_date, total_return, sharpe_ratio,
                      win_rate, profit_factor, total_trades, created_at
            FROM backtest_results WHERE symbol = %s
            ORDER BY created_at DESC LIMIT %s""",
            (symbol, limit),
        )
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "strategy": r[0], "start_date": r[1], "end_date": r[2],
                "total_return": r[3], "sharpe": r[4], "win_rate": r[5],
                "profit_factor": r[6], "trades": r[7], "date": str(r[8]),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("Failed to get backtest history: %s", exc)
        return []

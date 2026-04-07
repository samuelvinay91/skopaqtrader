"""Signal accuracy tracker — records every AI prediction and its outcome.

Tracks:
    - Per-symbol win rate (which stocks is the AI good/bad at?)
    - Confidence calibration (when AI says 75%, does it win 75%?)
    - Sector performance (IT, banking, energy — where's the edge?)
    - Regime performance (high VIX vs low VIX, trending vs ranging)
    - Time-of-day patterns (morning entries vs afternoon)
    - Stop-loss effectiveness (too tight? too loose?)
    - Holding period analysis (optimal duration per symbol)

All data persisted to Postgres for long-term learning.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Sector mapping for NIFTY 50 stocks
SECTOR_MAP = {
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy",
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "SBIN": "Banking",
    "KOTAKBANK": "Banking", "AXISBANK": "Banking", "INDUSINDBK": "Banking",
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
    "LT": "Infrastructure", "ULTRACEMCO": "Infrastructure", "GRASIM": "Infrastructure",
    "BHARTIARTL": "Telecom", "SUNPHARMA": "Pharma", "CIPLA": "Pharma",
    "TATAMOTORS": "Auto", "M&M": "Auto", "MARUTI": "Auto", "BAJAJ-AUTO": "Auto",
    "NTPC": "Power", "POWERGRID": "Power", "ADANIGREEN": "Power",
    "HINDALCO": "Metals", "TATASTEEL": "Metals", "JSWSTEEL": "Metals",
    "NESTLEIND": "FMCG", "HINDUNILVR": "FMCG", "ITC": "FMCG",
    "HDFC": "NBFC", "BAJFINANCE": "NBFC", "BAJAJFINSV": "NBFC",
}


@dataclass
class SignalRecord:
    """A recorded signal with outcome."""

    symbol: str
    signal: str  # BUY, SELL, HOLD
    confidence: int  # 0-100
    entry_price: float
    exit_price: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    won: bool = False
    sector: str = ""
    regime: str = ""  # "high_vix", "low_vix", "trending_up", "trending_down", "ranging"
    entry_hour: int = 0  # IST hour of entry
    holding_days: int = 0
    stop_loss_pct: float = 0.0
    stop_hit: bool = False
    target_hit: bool = False
    exit_reason: str = ""
    timestamp: str = ""


def _get_db():
    """Get Postgres connection."""
    try:
        import psycopg2
        url = os.environ.get("DATABASE_URL", "")
        if url:
            return psycopg2.connect(url)
    except Exception:
        pass
    return None


def _ensure_table():
    """Create signal_records table if needed."""
    conn = _get_db()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS signal_records (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20) NOT NULL,
                signal VARCHAR(10) NOT NULL,
                confidence INT DEFAULT 50,
                entry_price FLOAT,
                exit_price FLOAT DEFAULT 0,
                pnl FLOAT DEFAULT 0,
                pnl_pct FLOAT DEFAULT 0,
                won BOOLEAN DEFAULT false,
                sector VARCHAR(30),
                regime VARCHAR(30),
                entry_hour INT DEFAULT 0,
                holding_days INT DEFAULT 0,
                stop_loss_pct FLOAT DEFAULT 0,
                stop_hit BOOLEAN DEFAULT false,
                target_hit BOOLEAN DEFAULT false,
                exit_reason VARCHAR(50),
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_signal_symbol ON signal_records(symbol);
            CREATE INDEX IF NOT EXISTS idx_signal_sector ON signal_records(sector);
        """)
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.debug("Table create: %s", exc)


def record_signal(record: SignalRecord) -> None:
    """Save a signal record to the database."""
    _ensure_table()
    conn = _get_db()
    if not conn:
        logger.debug("No DB connection — signal not persisted")
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO signal_records
            (symbol, signal, confidence, entry_price, exit_price, pnl, pnl_pct,
             won, sector, regime, entry_hour, holding_days, stop_loss_pct,
             stop_hit, target_hit, exit_reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (record.symbol, record.signal, record.confidence,
             record.entry_price, record.exit_price, record.pnl, record.pnl_pct,
             record.won, record.sector, record.regime, record.entry_hour,
             record.holding_days, record.stop_loss_pct, record.stop_hit,
             record.target_hit, record.exit_reason),
        )
        conn.commit()
        conn.close()
        logger.info("Signal recorded: %s %s %s pnl=%.2f", record.signal, record.symbol, "WIN" if record.won else "LOSS", record.pnl)
    except Exception as exc:
        logger.warning("Failed to record signal: %s", exc)


# ── Analytics ────────────────────────────────────────────────────────────────


def get_symbol_accuracy(symbol: str) -> dict:
    """Get win rate and stats for a specific symbol."""
    conn = _get_db()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN won THEN 1 ELSE 0 END) as wins,
                AVG(pnl) as avg_pnl,
                AVG(pnl_pct) as avg_pnl_pct,
                AVG(confidence) as avg_confidence,
                AVG(holding_days) as avg_holding
            FROM signal_records WHERE symbol = %s""",
            (symbol,),
        )
        row = cur.fetchone()
        conn.close()
        if row and row[0] > 0:
            return {
                "symbol": symbol,
                "total_trades": row[0],
                "wins": row[1],
                "win_rate": round(row[1] / row[0] * 100, 1),
                "avg_pnl": round(row[2], 2),
                "avg_pnl_pct": round(row[3], 2),
                "avg_confidence": round(row[4], 1),
                "avg_holding_days": round(row[5], 1),
            }
        return {"symbol": symbol, "total_trades": 0}
    except Exception:
        return {}


def get_confidence_calibration() -> list[dict]:
    """Check: when AI says X% confidence, does it win X% of the time?"""
    conn = _get_db()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                CASE
                    WHEN confidence < 40 THEN '0-40'
                    WHEN confidence < 55 THEN '40-55'
                    WHEN confidence < 70 THEN '55-70'
                    WHEN confidence < 85 THEN '70-85'
                    ELSE '85-100'
                END as bucket,
                COUNT(*) as total,
                SUM(CASE WHEN won THEN 1 ELSE 0 END) as wins,
                AVG(confidence) as avg_stated_confidence
            FROM signal_records
            GROUP BY bucket
            ORDER BY bucket
        """)
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "confidence_range": r[0],
                "total": r[1],
                "wins": r[2],
                "actual_win_rate": round(r[2] / r[1] * 100, 1) if r[1] > 0 else 0,
                "stated_confidence": round(r[3], 1),
                "calibration_gap": round(r[3] - (r[2] / r[1] * 100 if r[1] > 0 else 0), 1),
            }
            for r in rows
        ]
    except Exception:
        return []


def get_sector_performance() -> list[dict]:
    """Get performance breakdown by sector."""
    conn = _get_db()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT sector,
                COUNT(*) as trades,
                SUM(CASE WHEN won THEN 1 ELSE 0 END) as wins,
                SUM(pnl) as total_pnl,
                AVG(pnl_pct) as avg_pnl_pct
            FROM signal_records
            WHERE sector IS NOT NULL AND sector != ''
            GROUP BY sector
            ORDER BY total_pnl DESC
        """)
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "sector": r[0],
                "trades": r[1],
                "wins": r[2],
                "win_rate": round(r[2] / r[1] * 100, 1) if r[1] > 0 else 0,
                "total_pnl": round(r[3], 2),
                "avg_pnl_pct": round(r[4], 2),
            }
            for r in rows
        ]
    except Exception:
        return []


def get_regime_performance() -> list[dict]:
    """Get performance by market regime."""
    conn = _get_db()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT regime,
                COUNT(*) as trades,
                SUM(CASE WHEN won THEN 1 ELSE 0 END) as wins,
                SUM(pnl) as total_pnl,
                AVG(pnl_pct) as avg_pnl_pct
            FROM signal_records
            WHERE regime IS NOT NULL AND regime != ''
            GROUP BY regime
            ORDER BY total_pnl DESC
        """)
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "regime": r[0],
                "trades": r[1],
                "win_rate": round(r[2] / r[1] * 100, 1) if r[1] > 0 else 0,
                "total_pnl": round(r[3], 2),
            }
            for r in rows
        ]
    except Exception:
        return []


def get_timing_patterns() -> list[dict]:
    """Get performance by entry hour."""
    conn = _get_db()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT entry_hour,
                COUNT(*) as trades,
                SUM(CASE WHEN won THEN 1 ELSE 0 END) as wins,
                AVG(pnl_pct) as avg_pnl_pct
            FROM signal_records
            WHERE entry_hour > 0
            GROUP BY entry_hour
            ORDER BY entry_hour
        """)
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "hour": f"{r[0]}:00 IST",
                "trades": r[1],
                "win_rate": round(r[2] / r[1] * 100, 1) if r[1] > 0 else 0,
                "avg_pnl_pct": round(r[3], 2),
            }
            for r in rows
        ]
    except Exception:
        return []


def get_stop_loss_analysis() -> dict:
    """Analyze stop-loss effectiveness."""
    conn = _get_db()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                SUM(CASE WHEN stop_hit THEN 1 ELSE 0 END) as stops_hit,
                COUNT(*) as total,
                AVG(CASE WHEN stop_hit THEN pnl_pct END) as avg_stop_loss_pct,
                AVG(CASE WHEN NOT stop_hit AND won THEN pnl_pct END) as avg_win_pct
            FROM signal_records
        """)
        row = cur.fetchone()
        conn.close()
        if row and row[1] > 0:
            return {
                "stops_hit": row[0],
                "total_trades": row[1],
                "stop_hit_rate": round(row[0] / row[1] * 100, 1),
                "avg_stop_loss": round(row[2] or 0, 2),
                "avg_win_when_not_stopped": round(row[3] or 0, 2),
            }
        return {}
    except Exception:
        return {}


def generate_learning_insights() -> str:
    """Generate a comprehensive learning report for the AI."""
    insights = []

    # Symbol accuracy
    conn = _get_db()
    if not conn:
        return "No trading data available for learning."

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT symbol,
                COUNT(*) as trades,
                SUM(CASE WHEN won THEN 1 ELSE 0 END) as wins,
                AVG(pnl_pct) as avg_pnl_pct
            FROM signal_records
            GROUP BY symbol
            HAVING COUNT(*) >= 3
            ORDER BY AVG(pnl_pct) DESC
        """)
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return "Less than 3 trades recorded. Need more data for learning."

        best = rows[0]
        worst = rows[-1]

        insights.append(
            f"Best performing: {best[0]} ({best[2]}/{best[1]} wins, {best[3]:+.1f}% avg)"
        )
        insights.append(
            f"Worst performing: {worst[0]} ({worst[2]}/{worst[1]} wins, {worst[3]:+.1f}% avg)"
        )

        # Confidence calibration
        calibration = get_confidence_calibration()
        for c in calibration:
            if abs(c["calibration_gap"]) > 15:
                if c["calibration_gap"] > 0:
                    insights.append(
                        f"OVERCONFIDENT in {c['confidence_range']}% range: "
                        f"stated {c['stated_confidence']:.0f}% but actual {c['actual_win_rate']:.0f}%"
                    )
                else:
                    insights.append(
                        f"UNDERCONFIDENT in {c['confidence_range']}% range: "
                        f"stated {c['stated_confidence']:.0f}% but actual {c['actual_win_rate']:.0f}%"
                    )

        # Sector insights
        sectors = get_sector_performance()
        for s in sectors:
            if s["trades"] >= 3:
                if s["win_rate"] > 60:
                    insights.append(f"STRONG in {s['sector']}: {s['win_rate']:.0f}% win rate")
                elif s["win_rate"] < 35:
                    insights.append(f"WEAK in {s['sector']}: {s['win_rate']:.0f}% win rate — avoid")

        # Stop-loss analysis
        sl = get_stop_loss_analysis()
        if sl and sl.get("stop_hit_rate", 0) > 50:
            insights.append(
                f"STOP-LOSS TOO TIGHT: {sl['stop_hit_rate']:.0f}% of trades hit stop. "
                "Consider widening stops."
            )

        return "\n".join(insights) if insights else "No actionable insights yet."

    except Exception as exc:
        return f"Learning analysis error: {exc}"

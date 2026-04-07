"""Strategy tearsheet generation via QuantStats.

Generates a professional HTML report with all metrics, charts, and
analysis — the same format used by institutional quant teams.

Usage::

    from skopaq.backtest.tearsheet import generate_tearsheet

    html_path = generate_tearsheet(backtest_result, benchmark="NIFTY 50")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from skopaq.backtest.engine import BacktestResult

logger = logging.getLogger(__name__)


def generate_tearsheet(
    result: BacktestResult,
    benchmark: str = "^NSEI",  # NIFTY 50
    output_path: str = "",
    title: str = "",
) -> str:
    """Generate a QuantStats HTML tearsheet.

    Args:
        result: BacktestResult with equity curve and daily returns.
        benchmark: Benchmark symbol for comparison (^NSEI = NIFTY 50).
        output_path: Where to save the HTML (default: /tmp/skopaq_tearsheet.html).
        title: Report title.

    Returns:
        Path to the generated HTML file.
    """
    import quantstats as qs

    if not output_path:
        output_path = f"/tmp/skopaq_tearsheet_{result.symbol}.html"

    if not title:
        title = f"SkopaqTrader — {result.symbol} Strategy Report"

    returns = result.daily_returns

    if len(returns) < 10:
        logger.warning("Too few data points for tearsheet (%d)", len(returns))
        return ""

    try:
        qs.reports.html(
            returns,
            benchmark=benchmark,
            output=output_path,
            title=title,
            download_filename=f"skopaq_{result.symbol}_tearsheet.html",
        )
        logger.info("Tearsheet saved: %s", output_path)
        return output_path

    except Exception as exc:
        logger.warning("Tearsheet generation failed: %s", exc)

        # Fallback: generate basic metrics report
        try:
            metrics = qs.reports.metrics(returns, mode="full", display=False)
            fallback_path = output_path.replace(".html", "_metrics.txt")
            with open(fallback_path, "w") as f:
                f.write(f"Strategy Report: {result.symbol}\n")
                f.write("=" * 50 + "\n\n")
                f.write(str(metrics))
            logger.info("Fallback metrics saved: %s", fallback_path)
            return fallback_path
        except Exception:
            return ""


def generate_snapshot(result: BacktestResult) -> str:
    """Generate a quick text snapshot of key metrics.

    Suitable for Telegram alerts or CLI output.
    """
    import quantstats as qs

    returns = result.daily_returns
    if len(returns) < 5:
        return "Insufficient data for snapshot"

    try:
        # Use quantstats for accurate calculations
        sharpe = qs.stats.sharpe(returns)
        sortino = qs.stats.sortino(returns)
        max_dd = qs.stats.max_drawdown(returns) * 100
        calmar = qs.stats.calmar(returns)
        win_rate = qs.stats.win_rate(returns) * 100
        volatility = qs.stats.volatility(returns) * 100
        cagr = qs.stats.cagr(returns) * 100

        lines = [
            f"Strategy Snapshot: {result.symbol}",
            f"Period: {result.start_date} → {result.end_date}",
            "",
            f"CAGR:       {cagr:+.2f}%",
            f"Sharpe:     {sharpe:.2f}",
            f"Sortino:    {sortino:.2f}",
            f"Calmar:     {calmar:.2f}",
            f"Max DD:     {max_dd:.2f}%",
            f"Volatility: {volatility:.2f}%",
            f"Win Rate:   {win_rate:.1f}%",
            f"Trades:     {result.total_trades}",
            f"P/F:        {result.profit_factor}",
        ]
        return "\n".join(lines)
    except Exception as exc:
        return f"Snapshot error: {exc}"

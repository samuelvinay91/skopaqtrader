"""Walk-Forward Optimization (WFO) — industry-standard anti-overfitting.

Trains strategy parameters on in-sample data, validates on out-of-sample,
rolls forward, and repeats. Produces Walk-Forward Efficiency (WFE) metric.

WFE > 70% = strategy parameters transfer well to unseen data.
WFE < 50% = likely overfit.

Usage::

    from skopaq.backtest.walk_forward import walk_forward_test

    results = walk_forward_test(
        signals_generator=my_signal_fn,
        ohlcv=historical_data,
        in_sample_months=6,
        out_of_sample_months=2,
    )
    print(f"WFE: {results.wfe_pct:.1f}%")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd

from skopaq.backtest.engine import (
    BacktestConfig,
    BacktestResult,
    run_backtest,
)

logger = logging.getLogger(__name__)


@dataclass
class WFOPeriod:
    """Results for a single walk-forward period."""

    period_index: int
    in_sample_start: str
    in_sample_end: str
    out_sample_start: str
    out_sample_end: str
    in_sample_return: float
    out_sample_return: float
    in_sample_sharpe: float
    out_sample_sharpe: float
    wfe: float  # out/in ratio


@dataclass
class WFOResult:
    """Complete walk-forward optimization results."""

    symbol: str
    total_periods: int
    periods: list[WFOPeriod] = field(default_factory=list)

    # Aggregate metrics
    wfe_pct: float = 0.0  # Walk-Forward Efficiency
    avg_oos_return: float = 0.0
    avg_oos_sharpe: float = 0.0
    consistency_pct: float = 0.0  # % of periods where OOS was profitable
    combined_oos_result: Optional[BacktestResult] = None


def walk_forward_test(
    signals_generator: Callable[[pd.DataFrame], pd.DataFrame],
    ohlcv: pd.DataFrame,
    symbol: str = "UNKNOWN",
    in_sample_months: int = 6,
    out_of_sample_months: int = 2,
    step_months: int = 2,
    config: Optional[BacktestConfig] = None,
) -> WFOResult:
    """Run walk-forward optimization.

    Args:
        signals_generator: Function that takes OHLCV DataFrame and returns
            signals DataFrame with [date, signal, confidence] columns.
            This is called separately for each in-sample period.
        ohlcv: Full historical OHLCV data.
        symbol: Symbol name.
        in_sample_months: Training period length.
        out_of_sample_months: Testing period length.
        step_months: How far to roll forward each period.
        config: Backtesting parameters.

    Returns:
        WFOResult with per-period and aggregate metrics.
    """
    if config is None:
        config = BacktestConfig()

    ohlcv = ohlcv.copy()
    ohlcv["Date"] = pd.to_datetime(ohlcv["Date"])
    ohlcv = ohlcv.sort_values("Date")

    start = ohlcv["Date"].min()
    end = ohlcv["Date"].max()

    periods: list[WFOPeriod] = []
    period_idx = 0
    current = start

    while True:
        # Define periods
        is_start = current
        is_end = current + pd.DateOffset(months=in_sample_months)
        oos_start = is_end
        oos_end = oos_start + pd.DateOffset(months=out_of_sample_months)

        if oos_end > end:
            break

        # Split data
        is_data = ohlcv[(ohlcv["Date"] >= is_start) & (ohlcv["Date"] < is_end)]
        oos_data = ohlcv[(ohlcv["Date"] >= oos_start) & (ohlcv["Date"] < oos_end)]

        if len(is_data) < 20 or len(oos_data) < 10:
            current += pd.DateOffset(months=step_months)
            continue

        # Generate signals for in-sample (train)
        is_signals = signals_generator(is_data)
        is_result = run_backtest(is_signals, is_data, config, symbol)

        # Apply same signal logic to out-of-sample (test)
        oos_signals = signals_generator(oos_data)
        oos_result = run_backtest(oos_signals, oos_data, config, symbol)

        # Walk-Forward Efficiency
        wfe = 0.0
        if is_result.total_return_pct != 0:
            wfe = (oos_result.total_return_pct / is_result.total_return_pct) * 100

        period = WFOPeriod(
            period_index=period_idx,
            in_sample_start=str(is_start.date()),
            in_sample_end=str(is_end.date()),
            out_sample_start=str(oos_start.date()),
            out_sample_end=str(oos_end.date()),
            in_sample_return=is_result.total_return_pct,
            out_sample_return=oos_result.total_return_pct,
            in_sample_sharpe=is_result.sharpe_ratio,
            out_sample_sharpe=oos_result.sharpe_ratio,
            wfe=wfe,
        )
        periods.append(period)

        logger.info(
            "WFO Period %d: IS=%.2f%% OOS=%.2f%% WFE=%.1f%%",
            period_idx, is_result.total_return_pct,
            oos_result.total_return_pct, wfe,
        )

        period_idx += 1
        current += pd.DateOffset(months=step_months)

    # Aggregate results
    result = WFOResult(
        symbol=symbol,
        total_periods=len(periods),
        periods=periods,
    )

    if periods:
        result.wfe_pct = round(np.mean([p.wfe for p in periods]), 1)
        result.avg_oos_return = round(np.mean([p.out_sample_return for p in periods]), 2)
        result.avg_oos_sharpe = round(np.mean([p.out_sample_sharpe for p in periods]), 2)
        result.consistency_pct = round(
            sum(1 for p in periods if p.out_sample_return > 0) / len(periods) * 100, 1
        )

    return result


def format_wfo_report(result: WFOResult) -> str:
    """Format WFO results as readable report."""
    lines = [
        f"WALK-FORWARD OPTIMIZATION: {result.symbol}",
        f"Periods: {result.total_periods}",
        "",
        "Aggregate:",
        f"  WFE: {result.wfe_pct:.1f}% {'PASS' if result.wfe_pct >= 70 else 'FAIL' if result.wfe_pct < 50 else 'MARGINAL'}",
        f"  Avg OOS Return: {result.avg_oos_return:+.2f}%",
        f"  Avg OOS Sharpe: {result.avg_oos_sharpe}",
        f"  Consistency: {result.consistency_pct:.0f}% periods profitable",
        "",
        "Period Details:",
    ]

    for p in result.periods:
        status = "OK" if p.wfe >= 70 else "WARN" if p.wfe >= 50 else "FAIL"
        lines.append(
            f"  [{p.period_index}] IS: {p.in_sample_start}→{p.in_sample_end} "
            f"({p.in_sample_return:+.2f}%) | "
            f"OOS: {p.out_sample_start}→{p.out_sample_end} "
            f"({p.out_sample_return:+.2f}%) | WFE: {p.wfe:.0f}% [{status}]"
        )

    return "\n".join(lines)

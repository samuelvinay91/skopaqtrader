"""Vectorized backtesting engine for SkopaqTrader strategies.

Runs the AI pipeline's signals against historical OHLCV data
to produce a complete equity curve with realistic fills.

Supports:
    - Long-only CNC (delivery)
    - Long-only MIS (intraday)
    - Configurable slippage, commission, position sizing
    - Indian market rules (circuit limits, T+1 settlement)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Backtesting parameters."""

    initial_capital: float = 1_000_000  # INR
    commission_pct: float = 0.001  # 0.1% round-trip (brokerage + charges)
    slippage_pct: float = 0.001  # 0.1% per trade
    risk_per_trade_pct: float = 0.01  # 1% of capital per trade
    max_positions: int = 5
    stop_loss_pct: float = 0.03  # 3% default stop
    target_pct: float = 0.06  # 6% default target
    trailing_stop_pct: float = 0.02  # 2% trailing stop (0 = disabled)
    circuit_limit_pct: float = 0.10  # 10% circuit breaker


@dataclass
class Trade:
    """A completed trade with entry/exit details."""

    symbol: str
    side: str  # BUY
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    pnl_pct: float
    exit_reason: str  # "target", "stop_loss", "trailing_stop", "signal", "eod"
    holding_days: int = 0


@dataclass
class BacktestResult:
    """Complete backtest output with equity curve and metrics."""

    config: BacktestConfig
    symbol: str
    start_date: str
    end_date: str
    total_bars: int

    # Equity curve
    equity_curve: pd.Series = field(default_factory=pd.Series)
    daily_returns: pd.Series = field(default_factory=pd.Series)

    # Trades
    trades: list[Trade] = field(default_factory=list)

    # Core metrics (computed after run)
    total_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_days: int = 0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    var_95: float = 0.0  # 95% Value at Risk
    cvar_95: float = 0.0  # Conditional VaR


def run_backtest(
    signals: pd.DataFrame,
    ohlcv: pd.DataFrame,
    config: Optional[BacktestConfig] = None,
    symbol: str = "UNKNOWN",
) -> BacktestResult:
    """Run a vectorized backtest on historical data with trading signals.

    Args:
        signals: DataFrame with columns [date, signal, confidence].
            signal: 1 (BUY), -1 (SELL), 0 (HOLD).
        ohlcv: DataFrame with columns [Date, Open, High, Low, Close, Volume].
        config: Backtesting parameters.
        symbol: Symbol name for reporting.

    Returns:
        BacktestResult with equity curve, trades, and metrics.
    """
    if config is None:
        config = BacktestConfig()

    # Merge signals with OHLCV
    ohlcv = ohlcv.copy()
    ohlcv["Date"] = pd.to_datetime(ohlcv["Date"])
    ohlcv = ohlcv.set_index("Date").sort_index()

    signals = signals.copy()
    signals["date"] = pd.to_datetime(signals["date"])
    signals = signals.set_index("date").sort_index()

    # Align
    data = ohlcv.join(signals[["signal", "confidence"]], how="left")
    data["signal"] = data["signal"].fillna(0).astype(int)
    data["confidence"] = data["confidence"].fillna(50)

    # Initialize
    capital = config.initial_capital
    position = 0  # Current shares held
    entry_price = 0.0
    entry_date = ""
    high_water = 0.0
    trades: list[Trade] = []
    equity = []

    for dt, row in data.iterrows():
        close = row["Close"]
        high = row["High"]
        low = row["Low"]
        sig = int(row["signal"])

        # Check circuit breaker
        if len(equity) > 0:
            prev_close = data.iloc[max(0, len(equity) - 1)]["Close"]
            if prev_close > 0 and abs(close - prev_close) / prev_close > config.circuit_limit_pct:
                equity.append(capital + position * close)
                continue

        # Position management (if holding)
        if position > 0:
            high_water = max(high_water, high)

            # Stop-loss check
            stop_price = entry_price * (1 - config.stop_loss_pct)
            if low <= stop_price:
                exit_price = stop_price * (1 - config.slippage_pct)
                pnl = (exit_price - entry_price) * position
                commission = exit_price * position * config.commission_pct
                pnl -= commission
                capital += position * exit_price - commission
                trades.append(Trade(
                    symbol=symbol, side="BUY",
                    entry_date=entry_date, exit_date=str(dt.date()),
                    entry_price=entry_price, exit_price=exit_price,
                    quantity=position, pnl=pnl,
                    pnl_pct=(exit_price / entry_price - 1) * 100,
                    exit_reason="stop_loss",
                    holding_days=(dt.date() - pd.to_datetime(entry_date).date()).days,
                ))
                position = 0
                entry_price = 0

            # Target check
            elif config.target_pct > 0:
                target_price = entry_price * (1 + config.target_pct)
                if high >= target_price:
                    exit_price = target_price * (1 - config.slippage_pct)
                    pnl = (exit_price - entry_price) * position
                    commission = exit_price * position * config.commission_pct
                    pnl -= commission
                    capital += position * exit_price - commission
                    trades.append(Trade(
                        symbol=symbol, side="BUY",
                        entry_date=entry_date, exit_date=str(dt.date()),
                        entry_price=entry_price, exit_price=exit_price,
                        quantity=position, pnl=pnl,
                        pnl_pct=(exit_price / entry_price - 1) * 100,
                        exit_reason="target",
                        holding_days=(dt.date() - pd.to_datetime(entry_date).date()).days,
                    ))
                    position = 0
                    entry_price = 0

            # Trailing stop check
            elif config.trailing_stop_pct > 0 and high_water > entry_price:
                trail_price = high_water * (1 - config.trailing_stop_pct)
                if low <= trail_price:
                    exit_price = trail_price * (1 - config.slippage_pct)
                    pnl = (exit_price - entry_price) * position
                    commission = exit_price * position * config.commission_pct
                    pnl -= commission
                    capital += position * exit_price - commission
                    trades.append(Trade(
                        symbol=symbol, side="BUY",
                        entry_date=entry_date, exit_date=str(dt.date()),
                        entry_price=entry_price, exit_price=exit_price,
                        quantity=position, pnl=pnl,
                        pnl_pct=(exit_price / entry_price - 1) * 100,
                        exit_reason="trailing_stop",
                        holding_days=(dt.date() - pd.to_datetime(entry_date).date()).days,
                    ))
                    position = 0
                    entry_price = 0

            # SELL signal
            elif sig == -1 and position > 0:
                exit_price = close * (1 - config.slippage_pct)
                pnl = (exit_price - entry_price) * position
                commission = exit_price * position * config.commission_pct
                pnl -= commission
                capital += position * exit_price - commission
                trades.append(Trade(
                    symbol=symbol, side="BUY",
                    entry_date=entry_date, exit_date=str(dt.date()),
                    entry_price=entry_price, exit_price=exit_price,
                    quantity=position, pnl=pnl,
                    pnl_pct=(exit_price / entry_price - 1) * 100,
                    exit_reason="signal",
                    holding_days=(dt.date() - pd.to_datetime(entry_date).date()).days,
                ))
                position = 0
                entry_price = 0

        # Entry logic
        if position == 0 and sig == 1:
            # Position sizing: risk-based
            risk_amount = capital * config.risk_per_trade_pct
            stop_distance = close * config.stop_loss_pct
            if stop_distance > 0:
                quantity = max(1, int(risk_amount / stop_distance))
            else:
                quantity = 1

            cost = close * quantity * (1 + config.slippage_pct + config.commission_pct)
            if cost <= capital:
                entry_price = close * (1 + config.slippage_pct)
                entry_date = str(dt.date())
                high_water = entry_price
                capital -= cost
                position = quantity

        equity.append(capital + position * close)

    # Close any remaining position at last close
    if position > 0:
        exit_price = data.iloc[-1]["Close"]
        pnl = (exit_price - entry_price) * position
        capital += position * exit_price
        trades.append(Trade(
            symbol=symbol, side="BUY",
            entry_date=entry_date, exit_date=str(data.index[-1].date()),
            entry_price=entry_price, exit_price=exit_price,
            quantity=position, pnl=pnl,
            pnl_pct=(exit_price / entry_price - 1) * 100,
            exit_reason="end_of_data",
        ))
        position = 0

    # Build equity curve
    equity_series = pd.Series(equity, index=data.index[:len(equity)])
    daily_returns = equity_series.pct_change().dropna()

    # Compute metrics
    result = BacktestResult(
        config=config,
        symbol=symbol,
        start_date=str(data.index[0].date()),
        end_date=str(data.index[-1].date()),
        total_bars=len(data),
        equity_curve=equity_series,
        daily_returns=daily_returns,
        trades=trades,
        total_trades=len(trades),
    )

    _compute_metrics(result)
    return result


def _compute_metrics(result: BacktestResult) -> None:
    """Compute all standard performance metrics."""
    returns = result.daily_returns
    equity = result.equity_curve

    if len(returns) < 2:
        return

    # Total return
    result.total_return_pct = (equity.iloc[-1] / equity.iloc[0] - 1) * 100

    # Annualized return (252 trading days)
    n_years = len(returns) / 252
    if n_years > 0:
        result.annual_return_pct = (
            (equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1
        ) * 100

    # Sharpe Ratio (risk-free rate = 6% for India)
    rf_daily = 0.06 / 252
    excess = returns - rf_daily
    if excess.std() > 0:
        result.sharpe_ratio = round(
            np.sqrt(252) * excess.mean() / excess.std(), 2
        )

    # Sortino Ratio (downside deviation only)
    downside = returns[returns < rf_daily] - rf_daily
    if len(downside) > 0 and downside.std() > 0:
        result.sortino_ratio = round(
            np.sqrt(252) * excess.mean() / downside.std(), 2
        )

    # Max Drawdown
    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    result.max_drawdown_pct = round(drawdown.min() * 100, 2)

    # Drawdown duration
    is_underwater = equity < peak
    if is_underwater.any():
        underwater_periods = (~is_underwater).cumsum()
        underwater_groups = is_underwater.groupby(underwater_periods)
        result.max_drawdown_duration_days = max(
            len(g) for _, g in underwater_groups if g.any()
        ) if any(g.any() for _, g in underwater_groups) else 0

    # Calmar Ratio
    if result.max_drawdown_pct != 0:
        result.calmar_ratio = round(
            result.annual_return_pct / abs(result.max_drawdown_pct), 2
        )

    # Trade statistics
    wins = [t for t in result.trades if t.pnl > 0]
    losses = [t for t in result.trades if t.pnl <= 0]
    result.winning_trades = len(wins)
    result.losing_trades = len(losses)

    if result.total_trades > 0:
        result.win_rate_pct = round(len(wins) / result.total_trades * 100, 1)

    if wins:
        result.avg_win = round(np.mean([t.pnl for t in wins]), 2)
    if losses:
        result.avg_loss = round(np.mean([t.pnl for t in losses]), 2)

    # Profit Factor
    gross_profit = sum(t.pnl for t in wins) if wins else 0
    gross_loss = abs(sum(t.pnl for t in losses)) if losses else 1
    result.profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0

    # VaR and CVaR (95%)
    if len(returns) > 10:
        sorted_returns = np.sort(returns.values)
        var_index = int(len(sorted_returns) * 0.05)
        result.var_95 = round(sorted_returns[var_index] * 100, 2)
        result.cvar_95 = round(sorted_returns[:var_index + 1].mean() * 100, 2)


def format_backtest_report(result: BacktestResult) -> str:
    """Format backtest results as a readable report."""
    lines = [
        f"BACKTEST REPORT: {result.symbol}",
        f"Period: {result.start_date} to {result.end_date} ({result.total_bars} bars)",
        f"Capital: Rs {result.config.initial_capital:,.0f}",
        "",
        "Performance:",
        f"  Total Return: {result.total_return_pct:+.2f}%",
        f"  Annual Return: {result.annual_return_pct:+.2f}%",
        f"  Sharpe Ratio: {result.sharpe_ratio}",
        f"  Sortino Ratio: {result.sortino_ratio}",
        f"  Calmar Ratio: {result.calmar_ratio}",
        "",
        "Risk:",
        f"  Max Drawdown: {result.max_drawdown_pct:.2f}%",
        f"  Max DD Duration: {result.max_drawdown_duration_days} days",
        f"  VaR (95%): {result.var_95:.2f}%",
        f"  CVaR (95%): {result.cvar_95:.2f}%",
        "",
        "Trades:",
        f"  Total: {result.total_trades}",
        f"  Winners: {result.winning_trades} ({result.win_rate_pct:.1f}%)",
        f"  Losers: {result.losing_trades}",
        f"  Avg Win: Rs {result.avg_win:,.2f}",
        f"  Avg Loss: Rs {result.avg_loss:,.2f}",
        f"  Profit Factor: {result.profit_factor}",
    ]

    # Quality assessment
    lines.append("")
    lines.append("Assessment:")
    if result.sharpe_ratio >= 1.5:
        lines.append("  Sharpe > 1.5 — STRONG")
    elif result.sharpe_ratio >= 1.0:
        lines.append("  Sharpe > 1.0 — ACCEPTABLE")
    else:
        lines.append("  Sharpe < 1.0 — WEAK (review strategy)")

    if result.win_rate_pct >= 55:
        lines.append(f"  Win Rate {result.win_rate_pct:.0f}% — GOOD")
    else:
        lines.append(f"  Win Rate {result.win_rate_pct:.0f}% — NEEDS IMPROVEMENT")

    if abs(result.max_drawdown_pct) > 20:
        lines.append(f"  Max DD {result.max_drawdown_pct:.0f}% — HIGH RISK")

    return "\n".join(lines)

"""Monte Carlo simulation for strategy robustness testing.

Generates 1,000+ equity curve scenarios by resampling historical returns.
Reveals if your edge is real or just luck from trade sequence ordering.

Key outputs:
    - Probability distribution of final returns
    - Worst-case drawdown at 95% confidence
    - Probability of ruin (equity going to zero)
    - Confidence intervals for Sharpe ratio
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class MonteCarloResult:
    """Monte Carlo simulation output."""

    n_simulations: int
    n_trades: int

    # Return distribution
    median_return_pct: float = 0.0
    p5_return_pct: float = 0.0   # 5th percentile (worst case)
    p25_return_pct: float = 0.0  # 25th percentile
    p75_return_pct: float = 0.0  # 75th percentile
    p95_return_pct: float = 0.0  # 95th percentile (best case)

    # Drawdown distribution
    median_max_dd_pct: float = 0.0
    worst_max_dd_pct: float = 0.0  # 95th percentile worst DD
    p5_max_dd_pct: float = 0.0

    # Sharpe distribution
    median_sharpe: float = 0.0
    p5_sharpe: float = 0.0
    p95_sharpe: float = 0.0

    # Risk of ruin
    probability_of_loss_pct: float = 0.0  # P(final equity < initial)
    probability_of_ruin_pct: float = 0.0  # P(equity hits 50% of initial)

    # Raw data for plotting
    all_final_returns: list[float] = field(default_factory=list)
    all_max_drawdowns: list[float] = field(default_factory=list)


def run_monte_carlo(
    trade_returns: list[float] | np.ndarray,
    initial_capital: float = 1_000_000,
    n_simulations: int = 1000,
    seed: int = 42,
) -> MonteCarloResult:
    """Run Monte Carlo simulation by resampling trade returns.

    Shuffles the order of historical trade returns to generate
    thousands of alternative equity curves. This reveals how
    sensitive the strategy is to trade sequence (luck vs edge).

    Args:
        trade_returns: List of per-trade P&L amounts (in INR).
        initial_capital: Starting capital.
        n_simulations: Number of scenarios to generate.
        seed: Random seed for reproducibility.

    Returns:
        MonteCarloResult with distribution statistics.
    """
    rng = np.random.default_rng(seed)
    returns = np.array(trade_returns)
    n_trades = len(returns)

    if n_trades < 5:
        logger.warning("Too few trades (%d) for Monte Carlo", n_trades)
        return MonteCarloResult(n_simulations=0, n_trades=n_trades)

    final_returns = []
    max_drawdowns = []
    sharpes = []
    ruin_count = 0
    loss_count = 0

    for _ in range(n_simulations):
        # Shuffle trade returns (bootstrap without time structure)
        shuffled = rng.permutation(returns)

        # Build equity curve
        equity = np.zeros(n_trades + 1)
        equity[0] = initial_capital
        for i, ret in enumerate(shuffled):
            equity[i + 1] = equity[i] + ret

        # Final return
        final_ret = (equity[-1] / initial_capital - 1) * 100
        final_returns.append(final_ret)

        # Max drawdown
        peak = np.maximum.accumulate(equity)
        dd = (equity - peak) / peak
        max_dd = dd.min() * 100
        max_drawdowns.append(max_dd)

        # Sharpe (daily approximation from trade returns)
        daily_equiv = shuffled / initial_capital
        if daily_equiv.std() > 0:
            sharpe = np.sqrt(252 / max(n_trades, 1)) * daily_equiv.mean() / daily_equiv.std()
            sharpes.append(sharpe)

        # Ruin check (equity drops below 50%)
        if equity.min() < initial_capital * 0.5:
            ruin_count += 1
        if equity[-1] < initial_capital:
            loss_count += 1

    final_returns = np.array(final_returns)
    max_drawdowns = np.array(max_drawdowns)
    sharpes = np.array(sharpes) if sharpes else np.array([0])

    return MonteCarloResult(
        n_simulations=n_simulations,
        n_trades=n_trades,
        median_return_pct=round(float(np.median(final_returns)), 2),
        p5_return_pct=round(float(np.percentile(final_returns, 5)), 2),
        p25_return_pct=round(float(np.percentile(final_returns, 25)), 2),
        p75_return_pct=round(float(np.percentile(final_returns, 75)), 2),
        p95_return_pct=round(float(np.percentile(final_returns, 95)), 2),
        median_max_dd_pct=round(float(np.median(max_drawdowns)), 2),
        worst_max_dd_pct=round(float(np.percentile(max_drawdowns, 5)), 2),
        p5_max_dd_pct=round(float(np.percentile(max_drawdowns, 5)), 2),
        median_sharpe=round(float(np.median(sharpes)), 2),
        p5_sharpe=round(float(np.percentile(sharpes, 5)), 2),
        p95_sharpe=round(float(np.percentile(sharpes, 95)), 2),
        probability_of_loss_pct=round(loss_count / n_simulations * 100, 1),
        probability_of_ruin_pct=round(ruin_count / n_simulations * 100, 1),
        all_final_returns=final_returns.tolist(),
        all_max_drawdowns=max_drawdowns.tolist(),
    )


def format_monte_carlo_report(result: MonteCarloResult) -> str:
    """Format Monte Carlo results as readable report."""
    lines = [
        f"MONTE CARLO SIMULATION ({result.n_simulations} scenarios, {result.n_trades} trades)",
        "",
        "Return Distribution:",
        f"   5th pct (worst): {result.p5_return_pct:+.2f}%",
        f"  25th pct:         {result.p25_return_pct:+.2f}%",
        f"  Median:           {result.median_return_pct:+.2f}%",
        f"  75th pct:         {result.p75_return_pct:+.2f}%",
        f"  95th pct (best):  {result.p95_return_pct:+.2f}%",
        "",
        "Drawdown Distribution:",
        f"  Median Max DD:     {result.median_max_dd_pct:.2f}%",
        f"  Worst-case (95%):  {result.worst_max_dd_pct:.2f}%",
        "",
        "Sharpe Distribution:",
        f"  5th pct:  {result.p5_sharpe}",
        f"  Median:   {result.median_sharpe}",
        f"  95th pct: {result.p95_sharpe}",
        "",
        "Risk Assessment:",
        f"  P(Loss):  {result.probability_of_loss_pct:.1f}%",
        f"  P(Ruin):  {result.probability_of_ruin_pct:.1f}%",
        "",
    ]

    # Verdict
    if result.probability_of_ruin_pct > 10:
        lines.append("VERDICT: HIGH RISK — probability of ruin > 10%")
    elif result.p5_return_pct < -20:
        lines.append("VERDICT: MODERATE RISK — worst-case return < -20%")
    elif result.median_sharpe > 1.0:
        lines.append("VERDICT: ROBUST — median Sharpe > 1.0, edge appears real")
    else:
        lines.append("VERDICT: ACCEPTABLE — monitor closely")

    return "\n".join(lines)

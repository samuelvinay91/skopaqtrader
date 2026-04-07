"""Strategy refinement — backtesting, walk-forward optimization, Monte Carlo.

Industry-standard framework:
1. Backtester: Vectorized OHLCV backtesting with slippage/commission
2. Metrics: Sharpe, Sortino, Calmar, max drawdown, VaR, CVaR, win rate
3. Walk-Forward: Rolling in-sample/out-of-sample optimization
4. Monte Carlo: Bootstrap resampling for robustness testing
5. Tearsheet: QuantStats HTML report generation
"""

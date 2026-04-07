# Quantitative Learning Engine

The learning engine tracks every AI prediction and its outcome, building a data-driven understanding of what works and what doesn't.

## What It Tracks

| Metric | Question It Answers |
|--------|-------------------|
| **Symbol Accuracy** | Which stocks is the AI best/worst at? |
| **Confidence Calibration** | When AI says 75%, does it win 75%? |
| **Sector Performance** | Banking vs IT vs Energy — where's the edge? |
| **Regime Performance** | High VIX vs low VIX — different strategies? |
| **Timing Patterns** | Morning entries vs afternoon — which works? |
| **Stop-Loss Analysis** | Are stops too tight (hit before recovery)? |
| **Holding Period** | Optimal days to hold per stock? |

## How It Works

```
Trade Executed → Record: symbol, confidence, entry, sector, regime, hour
        ↓
Trade Closed → Update: exit price, P&L, won/lost, holding days
        ↓
Learning Engine → Analyze patterns across all trades
        ↓
Generate Insights → "OVERCONFIDENT on IT stocks", "Stops too tight on RELIANCE"
        ↓
Inject into Agent → Next analysis uses these insights
```

## MCP Tools

- `get_learning_insights` — Full learning report with all patterns
- `get_symbol_stats RELIANCE` — Per-symbol performance stats

## Database Tables

- `signal_records` — Every signal with outcome (Fly.io Postgres)

## Self-Correction

The learning engine enables **self-correction**:

- If AI is overconfident (says 80% but wins 50%), it learns to lower confidence
- If stops are hit 60% of the time, it widens stops automatically
- If a sector consistently loses, the AI deprioritizes it in scans

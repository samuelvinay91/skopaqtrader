---
name: trade
description: Full trade workflow — Claude analyzes the stock, validates safety, and executes (paper mode) after user confirmation.
argument-hint: <SYMBOL>
user-invocable: true
allowed-tools: mcp__skopaq__get_quote mcp__skopaq__get_historical mcp__skopaq__get_positions mcp__skopaq__get_funds mcp__skopaq__check_safety mcp__skopaq__place_order WebSearch
---

# Execute Trade — Claude-Native Analysis + Execution

You ARE the trader. Analyze the stock yourself using live data, then execute if the user confirms.

## Your Task

### Phase 1: Analysis (use /analyze approach)

1. Fetch live quote and historical data for **$ARGUMENTS**
2. Search for recent news
3. Run your own technical + fundamental analysis
4. Generate a BUY/SELL/HOLD signal with confidence

### Phase 2: Pre-Trade Validation

If your signal is BUY or SELL:

1. Call `mcp__skopaq__get_funds` to check available capital
2. Calculate position size:
   - Risk 1% of available capital per trade
   - Stop distance = entry - stop_loss
   - Quantity = floor(risk_amount / stop_distance)
3. Call `mcp__skopaq__check_safety` to validate:
   - symbol, quantity, price, side (BUY or SELL)
4. If safety check fails, explain why and adjust

### Phase 3: User Confirmation (MANDATORY)

Present the trade plan clearly:

```
TRADE PLAN: BUY RELIANCE
  Entry:     ₹2,500.00
  Stop Loss: ₹2,410.00 (-3.6%)
  Target:    ₹2,700.00 (+8.0%)
  Quantity:  40 shares
  Risk:      ₹3,600 (0.36% of capital)
  R:R Ratio: 2.2:1
  Mode:      PAPER
  Safety:    PASSED
```

**Ask**: "Shall I execute this trade in paper mode? (y/n)"

### Phase 4: Execution (only after user says yes)

Call `mcp__skopaq__place_order` with the confirmed parameters.

**NEVER execute without explicit user confirmation.**
Paper mode is always the default.

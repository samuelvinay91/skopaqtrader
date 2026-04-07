# Swing Trading

SkopaqTrader automates CNC (Cash and Carry) swing trades using GTT orders for both entry and exit. The goal is set-and-forget trading at key support/resistance levels.

## What Is CNC Swing Trading?

Swing trades hold positions for days to weeks, targeting price swings between support and resistance. CNC (delivery) orders mean you own the shares outright -- no margin expiry risk.

```
Support (buy zone)  ────────────────  Rs 2,400
                         ▲
                         │  Your trade lives here
                         ▼
Resistance (sell zone) ──────────────  Rs 2,600
```

## The Full Flow

### Step 1: Identify the Setup

Use `/scan` or `/analyze` to find stocks at key levels:

```
/scan
```

Look for stocks near well-defined support with:

- RSI approaching oversold (< 35)
- Volume declining on pullback
- Strong fundamentals (not a falling knife)

### Step 2: Set Up the Swing Trade

Once you identify a candidate:

```
/trade RELIANCE
```

Or ask Claude directly:

> Set up a swing trade on RELIANCE. Entry at Rs 2,400, target Rs 2,600, stop-loss Rs 2,350, quantity 20 shares.

Claude calls `setup_swing_trade`:

```
mcp__skopaq__setup_swing_trade(
    symbol="RELIANCE",
    entry_price=2400.0,
    target_price=2600.0,
    stop_loss_price=2350.0,
    quantity=20
)
```

### Step 3: GTT BUY Activates

A GTT BUY order is placed at Rs 2,400. When RELIANCE drops to this price:

1. Zerodha automatically executes the buy
2. You receive a Telegram notification
3. Shares are credited to your demat account (CNC delivery)

### Step 4: Set OCO Exit

After the buy fills, set up the automated exit:

> Place a GTT OCO sell for RELIANCE: target Rs 2,600, stop-loss Rs 2,350, 20 shares.

```
mcp__skopaq__place_gtt_order(
    symbol="RELIANCE",
    action="SELL",
    target_price=2600.0,
    stop_loss_price=2350.0,
    quantity=20
)
```

### Step 5: Automated Exit

The OCO order watches both levels simultaneously:

- If RELIANCE hits Rs 2,600 -- **sell at target** (profit Rs 4,000)
- If RELIANCE hits Rs 2,350 -- **sell at stop-loss** (loss Rs 1,000)
- Risk-reward: 1:4

## Position Sizing

SkopaqTrader uses the 1% risk rule:

```
Available capital:    Rs 10,00,000
Risk per trade:       1% = Rs 10,000
Stop distance:        Rs 2,400 - Rs 2,350 = Rs 50
Position size:        Rs 10,000 / Rs 50 = 200 shares
Order value:          200 x Rs 2,400 = Rs 4,80,000
```

!!! warning "Safety limits apply"
    The `SafetyChecker` enforces max position size (15% of capital) and max order value (Rs 5,00,000). If your calculated size exceeds these limits, it will be capped.

## Finding Swing Setups

### Technical Criteria

| Indicator | Bullish Setup | What to Look For |
|-----------|---------------|------------------|
| Price action | At support | Bounce off 50/200 SMA |
| RSI | < 35 | Oversold condition |
| MACD | Bullish crossover | Signal line cross |
| Volume | Declining on pullback | Lack of selling pressure |
| Bollinger Bands | At lower band | Mean reversion candidate |

### Using the Scanner

```
/scan 10
```

Filter the results for stocks with:

- Change% between -1% and -3% (pulling back but not crashing)
- Above 200-day SMA (long-term uptrend intact)
- High relative volume (institutional interest)

## Example: Full Workflow

```
1. /scan                      → Find candidates
2. /analyze HDFCBANK          → Deep analysis
3. /quote HDFCBANK            → Check current price
4. setup_swing_trade(          → Automate entry + exit plan
     symbol="HDFCBANK",
     entry=1500, target=1620,
     stop_loss=1470, quantity=30
   )
5. Wait for GTT BUY trigger   → Telegram notification
6. place_gtt_order(SELL, ...)  → Set OCO exit
7. Wait for exit trigger       → Telegram notification
8. save_trade_reflection(...)  → Store lesson for future trades
```

## Monitoring Active Swings

Check your active GTT orders:

> Show my active GTT orders.

Check open positions:

```
/portfolio
```

## Risk Management

1. **Never risk more than 1-2% per trade** -- Position size accordingly
2. **Always set the OCO sell immediately** -- Do not leave positions unprotected
3. **Review weekly** -- Cancel GTT buys if the setup has changed
4. **Avoid earnings** -- Do not swing trade through earnings announcements
5. **Maximum 3-5 concurrent swings** -- Enforced by `max_open_positions` safety rule

!!! tip "Post-trade reflection"
    After each swing trade completes, use `save_trade_reflection` to store the outcome. The agent memory system learns from your wins and losses, improving future analysis.

# GTT Orders

GTT (Good Till Triggered) orders are persistent orders that live on Zerodha's servers and execute automatically when the trigger price is hit. No monitoring needed -- they work 24/7 for up to one year.

## What Are GTT Orders?

Unlike regular orders that expire at end of day, GTT orders remain active until:

- The trigger price is hit (order executes)
- You cancel them manually
- They expire after 1 year

GTT orders are ideal for:

- **Buy at support** -- Set a trigger to buy when price drops to a key level
- **Automated exits** -- OCO (One-Cancels-Other) for target + stop-loss
- **Swing trading** -- Set and forget entry/exit levels

## Types of GTT Orders

### Single Trigger (GTT BUY)

Buy when price drops to a specific level.

```
GTT BUY HDFCBANK at Rs 1,450
→ When HDFCBANK hits Rs 1,450, buy at market
```

### OCO (One-Cancels-Other) SELL

Set two exit triggers. Whichever hits first executes, cancelling the other.

```
OCO SELL HDFCBANK
  Target:    Rs 1,650 (sell at profit)
  Stop-Loss: Rs 1,400 (cut loss)
→ First trigger hit → sell executes → other cancelled
```

## Using GTT via Claude Code

### Place a GTT Buy

> Set a GTT order to buy 50 shares of HDFCBANK when it drops to Rs 1,450.

Claude calls:

```
mcp__skopaq__place_gtt_order(
    symbol="HDFCBANK",
    action="BUY",
    trigger_price=1450.0,
    quantity=50
)
```

### Place a GTT OCO Sell

> Set a GTT sell for my HDFCBANK position: target Rs 1,650, stop-loss Rs 1,400.

```
mcp__skopaq__place_gtt_order(
    symbol="HDFCBANK",
    action="SELL",
    target_price=1650.0,
    stop_loss_price=1400.0,
    quantity=50
)
```

### List Active GTT Orders

> Show my active GTT orders.

```
mcp__skopaq__list_gtt_orders()
```

## MCP Tools

| Tool | Purpose | Key Args |
|------|---------|----------|
| `place_gtt_order` | Place single-trigger BUY or OCO SELL | `symbol`, `action`, `trigger_price`, `target_price`, `stop_loss_price`, `quantity` |
| `list_gtt_orders` | List all active GTT orders | none |
| `setup_swing_trade` | Complete swing setup (GTT BUY + planned OCO SELL) | `symbol`, `entry_price`, `target_price`, `stop_loss_price`, `quantity` |

## Example: Complete Swing Setup

> Set up a swing trade on RELIANCE: buy at Rs 2,400 support, target Rs 2,600, stop-loss Rs 2,350.

Claude calls `setup_swing_trade`:

```json
{
  "success": true,
  "type": "SWING_TRADE_SETUP",
  "symbol": "RELIANCE",
  "entry": 2400.0,
  "target": 2600.0,
  "stop_loss": 2350.0,
  "quantity": 10,
  "risk_reward": "1:4.0",
  "message": "Swing trade set for RELIANCE:\n  BUY trigger: Rs 2,400.00 (GTT active)\n  Target: Rs 2,600.00 (+8.3%)\n  Stop Loss: Rs 2,350.00 (-2.1%)\n  R:R = 1:4.0\n\nAfter BUY fills, set OCO SELL via: place_gtt_order SELL RELIANCE target=2600 stop_loss=2350"
}
```

!!! note "Two-step process"
    `setup_swing_trade` places the GTT BUY immediately. After the buy triggers, you need to manually set the OCO SELL (the tool provides the exact command).

## Notifications

GTT events trigger automatic Telegram notifications:

| Event | Notification |
|-------|-------------|
| GTT placed | Confirmation with trigger details |
| GTT triggered | Alert that order executed |
| GTT cancelled | Confirmation of cancellation |
| GTT expired | Warning that order expired |

These are sent via `skopaq/notifications.py` using `notify_gtt_event()`.

## Architecture

GTT orders are implemented in `skopaq/options/gtt.py`:

- `place_gtt_buy()` -- Single-trigger buy at support
- `place_gtt_oco_sell()` -- OCO sell with target + stop-loss
- `list_gtts()` -- Fetch active GTT orders
- `format_gtt_for_telegram()` -- Format for notification display

All GTT operations use the `KiteClient` which wraps Zerodha's `kiteconnect` SDK.

!!! warning "Requires Kite Connect"
    GTT orders are a Zerodha-specific feature. You must be logged into Kite via the OAuth flow before using these tools.

## Best Practices

1. **Always set OCO exits** -- After a GTT BUY fills, immediately set the OCO SELL
2. **Use support/resistance levels** -- Set triggers at technically significant prices
3. **Check active GTTs regularly** -- Market conditions change; old triggers may no longer be valid
4. **Account for slippage** -- GTT executes at market price after trigger, not at the trigger price exactly
5. **Risk-reward ratio** -- Aim for at least 1:2 risk-reward on swing trades

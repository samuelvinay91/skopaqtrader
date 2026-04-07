# Scheduled Jobs

The Telegram bot runs three scheduled jobs daily during market hours. These are configured in `skopaq/telegram_bot.py` using `python-telegram-bot`'s built-in job queue.

## Job Schedule

| Time (IST) | Time (UTC) | Job | Description |
|------------|------------|-----|-------------|
| 09:00 | 03:30 | Pre-Market Login | Kite Connect login reminder |
| 09:25 | 03:55 | Market Scan | Auto-scan top 10 stocks |
| 15:35 | 10:05 | EOD Summary | End-of-day P&L report |

## Pre-Market Login (09:00 IST)

Sends a reminder to connect to Zerodha if the Kite access token is not set.

**What it does:**

1. Checks if `get_access_token()` returns a valid token
2. If connected: sends "Kite connected -- ready for market open"
3. If not connected: sends login link `https://skopaq-trader.fly.dev/api/kite/login`

**Why 09:00?**

NSE pre-open session starts at 09:00. Logging in early ensures the token is ready before 09:15 when regular trading begins.

```python
# IST 9:00 = UTC 3:30
app.job_queue.run_daily(
    job_pre_market_login,
    time=dt_time(hour=3, minute=30, tzinfo=timezone.utc),
    name="pre_market_login",
)
```

## Market Scan (09:25 IST)

Scans NIFTY 50 top stocks and sends the results to all registered chats.

**What it does:**

1. Verifies Kite is connected (sends login prompt if not)
2. Fetches live quotes for 10 blue-chip stocks:
   RELIANCE, HDFCBANK, ICICIBANK, INFY, TCS, SBIN, LT, BHARTIARTL, WIPRO, NTPC
3. Sorts by absolute change% (top movers)
4. Sends formatted scan results

**Example output:**

```
Market Scan (09:25 IST)

  RELIANCE: Rs 2,485.50 (+1.23%) Vol: 12,34,567
  HDFCBANK: Rs 1,567.80 (+0.89%) Vol: 8,45,230
  SBIN: Rs 756.30 (-0.45%) Vol: 15,67,890
  TCS: Rs 3,750.00 (+0.32%) Vol: 3,21,456
  ...

Top pick: RELIANCE (+1.23%)

Reply 'analyze SYMBOL' for deep analysis
Reply 'trade SYMBOL' to execute
```

**Why 09:25?**

Prices settle about 10 minutes after market open (09:15). Scanning at 09:25 gives enough data for meaningful volume and direction signals.

!!! note "Customizing the watchlist"
    The scanned stocks are hardcoded in the `job_market_scan` function. To customize, edit the `symbols` list in `skopaq/telegram_bot.py`.

## EOD Summary (15:35 IST)

Sends end-of-day portfolio summary after market close.

**What it does:**

1. Checks Kite connection (skips if not connected)
2. Fetches open positions and funds
3. Calculates total day P&L
4. Sends formatted summary

**Example output:**

```
Market Closed -- EOD Summary

Cash: Rs 9,87,654.00

Open Positions (2):
  RELIANCE: 10x @ 2400.00 P&L: Rs +855.00
  TCS: 5x @ 3800.00 P&L: Rs -250.00

Total Day P&L: Rs +605.00
```

**Why 15:35?**

NSE regular trading ends at 15:30. The 5-minute buffer ensures all orders are settled and final prices are available.

## How Jobs Are Registered

All three jobs use `run_daily` from `python-telegram-bot`'s `JobQueue`:

```python
from datetime import time as dt_time, timezone

# IST 9:00 = UTC 3:30
app.job_queue.run_daily(
    job_pre_market_login,
    time=dt_time(hour=3, minute=30, tzinfo=timezone.utc),
    name="pre_market_login",
)

# IST 9:25 = UTC 3:55
app.job_queue.run_daily(
    job_market_scan,
    time=dt_time(hour=3, minute=55, tzinfo=timezone.utc),
    name="market_scan",
)

# IST 15:35 = UTC 10:05
app.job_queue.run_daily(
    job_eod_summary,
    time=dt_time(hour=10, minute=5, tzinfo=timezone.utc),
    name="eod_summary",
)
```

!!! warning "UTC times"
    All times are specified in UTC. IST = UTC + 5:30. If you change these, remember to convert correctly.

## Notification Routing

Scheduled jobs send messages to all registered chat IDs in `alert_chat_ids`. A chat ID is registered when a user sends `/start` to the bot.

```
/start → chat_id added to alert_chat_ids
                          │
                          ▼
Scheduled jobs → send to all registered chat_ids
```

If no chat IDs are registered, scheduled jobs run silently (no errors, just no output).

## Adding Custom Jobs

To add a new scheduled job, follow this pattern in `skopaq/telegram_bot.py`:

```python
async def job_custom(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Your custom job description."""
    for chat_id in list(alert_chat_ids):
        await context.bot.send_message(
            chat_id=chat_id,
            text="Your scheduled message here",
        )

# Register in main():
app.job_queue.run_daily(
    job_custom,
    time=dt_time(hour=6, minute=0, tzinfo=timezone.utc),  # 11:30 IST
    name="custom_job",
)
```

## Weekday-Only Execution

The scheduled jobs run every day including weekends. Since the market is closed on weekends, the scan and EOD jobs will either return empty data or skip gracefully (Kite token may be expired). For production use, consider adding a weekday check at the top of each job function.

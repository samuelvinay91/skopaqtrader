# Kite Connect (Zerodha) Setup Guide

This guide walks you through setting up Kite Connect as your broker in SkopaqTrader — from creating a Zerodha developer app to placing your first paper trade.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Create a Kite Connect App](#step-1-create-a-kite-connect-app)
3. [Step 2: Configure SkopaqTrader](#step-2-configure-skopaqtrader)
4. [Step 3: Authenticate (Get Access Token)](#step-3-authenticate-get-access-token)
5. [Step 4: Verify the Setup](#step-4-verify-the-setup)
6. [Step 5: Paper Trading](#step-5-paper-trading)
7. [Step 6: Live Trading](#step-6-live-trading)
8. [Daily Login Flow](#daily-login-flow)
9. [Token Lifecycle](#token-lifecycle)
10. [Troubleshooting](#troubleshooting)
11. [API Reference (Quick)](#api-reference-quick)

---

## Prerequisites

- A **Zerodha trading account** (demat + trading)
- A **Kite Connect developer subscription** (one-time fee of Rs. 2,000/month from Zerodha)
- Python 3.11+ with SkopaqTrader installed

> **Note:** Kite Connect is a paid API product from Zerodha. You need an active subscription at [developers.kite.trade](https://developers.kite.trade). This is separate from your regular Zerodha trading account.

---

## Step 1: Create a Kite Connect App

1. Go to [developers.kite.trade](https://developers.kite.trade) and log in with your Zerodha credentials.

2. Click **Create new app** and fill in:

   | Field | Value |
   |-------|-------|
   | **App name** | `SkopaqTrader` (or any name) |
   | **Type** | `Connect` |
   | **Redirect URL** | `http://127.0.0.1:5000/callback` |
   | **Description** | Algorithmic trading platform |

   > The redirect URL is where Zerodha sends you after login. For local development, `http://127.0.0.1:5000/callback` works. You'll extract the `request_token` from this URL manually.

3. After creation, note down:
   - **API Key** (e.g., `xk8v2abc3def4g`)
   - **API Secret** (e.g., `h7j9k2m4n6p8q0...` — a long alphanumeric string)

   These are on your app's detail page at developers.kite.trade.

---

## Step 2: Configure SkopaqTrader

Add these to your `.env` file at the project root:

```bash
# ===== Broker Selection =====
SKOPAQ_BROKER=kite

# ===== Kite Connect Credentials =====
SKOPAQ_KITE_API_KEY=your_api_key_here
SKOPAQ_KITE_API_SECRET=your_api_secret_here
```

That's it for config. The access token is generated via the login flow below.

---

## Step 3: Authenticate (Get Access Token)

Kite Connect uses OAuth2. You must log in via browser once per trading day (tokens expire at ~6:00 AM IST next day).

### Option A: CLI Flow (Recommended)

```bash
# 1. Get the login URL
skopaq kite login-url
# Output: Open this URL in your browser:
# https://kite.zerodha.com/connect/login?v=3&api_key=xk8v2abc3def4g

# 2. Open the URL in your browser
#    - Log in with your Zerodha credentials
#    - Complete 2FA (TOTP/PIN)
#    - You'll be redirected to your redirect URL with a request_token:
#    http://127.0.0.1:5000/callback?request_token=abc123xyz&status=success

# 3. Copy the request_token value and run:
skopaq kite session abc123xyz
# Output: Kite session established. Token: a1b2c3d4...

# 4. Verify
skopaq kite status
# Output: Kite token valid. Expires in 18:30:00 (at 2026-03-29 06:00:00+05:30)
```

### Option B: Direct Token (Advanced)

If you obtain an access token through your own OAuth flow or automation:

```bash
skopaq kite set-token your_access_token_here
```

### Option C: Environment Variable

Set the token directly in `.env` (useful for CI/cron):

```bash
SKOPAQ_KITE_ACCESS_TOKEN=your_access_token_here
```

> **Warning:** Access tokens expire daily at ~6:00 AM IST. You must re-authenticate each trading day.

---

## Step 4: Verify the Setup

```bash
# Check overall system status (shows broker, token health, LLMs)
skopaq status

# Expected output includes:
# Broker: kite
# Token: Valid (expires in 18:30:00)
```

---

## Step 5: Paper Trading

Paper trading works **with or without a Kite token**. When a token is available, paper mode uses real Kite market data. Without a token, it falls back to yfinance (free, no credentials).

```bash
# Analyze a stock (no execution)
skopaq analyze RELIANCE

# Paper trade (simulated execution with real market data)
skopaq trade RELIANCE

# Run the scanner in paper mode
skopaq scan

# Full autonomous paper session
skopaq daemon --once --paper
```

### How Paper Mode Gets Market Data

```
Priority 1: Kite Connect API  (if token available — best data, real bid/ask)
     |
     v  (falls back if no token)
Priority 2: yfinance           (free, no credentials — delayed data)
     |
     v  (falls back if yfinance fails)
Priority 3: Cached quotes       (last known price)
```

The `MarketDataProvider` handles this automatically. You never need to configure the fallback — it just works.

---

## Step 6: Live Trading

> **WARNING:** Live trading uses real money. Start with paper mode until you are confident in the system. You are solely responsible for all trades.

```bash
# Set live mode in .env
SKOPAQ_TRADING_MODE=live
SKOPAQ_BROKER=kite

# Or pass --live flag (requires confirmation)
skopaq trade RELIANCE --live

# Autonomous live session (requires --confirm-live for cron)
skopaq daemon --once --live --confirm-live
```

### Pre-Live Checklist

- [ ] Paper traded successfully for at least 1 week
- [ ] Kite token is valid (`skopaq kite status`)
- [ ] Safety rules reviewed in `skopaq/constants.py`
- [ ] Position limits appropriate for your capital
- [ ] Stop-loss rules enabled (`require_stop_loss: true`)

---

## Daily Login Flow

Kite tokens expire at ~6:00 AM IST every day. For daily trading:

### Manual (Interactive)

```bash
# Each morning before market open (9:15 AM IST):
skopaq kite login-url          # Open URL in browser
# Complete login + 2FA
skopaq kite session <token>    # Exchange request_token
skopaq kite status             # Verify
```

### Automated (Advanced)

For unattended daemon operation, you need to automate the login flow. Common approaches:

1. **Selenium/Playwright script** — Automate the browser login + 2FA
2. **TOTP automation** — Generate TOTP codes programmatically using your Zerodha authenticator secret
3. **Kite Publisher** — Zerodha's postback service can be configured to auto-generate tokens

Example automation skeleton (not included — you must build this for your setup):

```python
# pseudocode for automated login
import pyotp

totp = pyotp.TOTP("your_totp_secret")
# 1. POST to kite login with user_id + password
# 2. POST TOTP code
# 3. Extract request_token from redirect
# 4. Call: skopaq kite session <request_token>
```

> **Security:** Never store your Zerodha password or TOTP secret in the codebase. Use a secrets manager or environment variables.

---

## Token Lifecycle

```
Browser Login → request_token (single-use, expires in minutes)
     |
     v
POST /session/token → access_token (valid until ~6 AM IST next day)
     |
     v
Stored encrypted in ~/.skopaq/kite_token.enc
     |
     v
Used for all API calls: Authorization: token {api_key}:{access_token}
```

| Token | Lifetime | How to Get |
|-------|----------|------------|
| `request_token` | ~5 minutes | Browser login redirect URL |
| `access_token` | Until ~6:00 AM IST | `skopaq kite session <request_token>` |

### Token Storage

- Encrypted at rest using Fernet (AES-128-CBC)
- Stored in `~/.skopaq/kite_token.enc`
- Encryption key in `~/.skopaq/kite_token.key` (chmod 600)
- Expiry warnings at 2h, 1h, 30min, 10min before expiry

---

## Troubleshooting

### "No Kite token stored"

```bash
skopaq kite login-url    # Get login URL
# Complete browser login
skopaq kite session <request_token>
```

### "Kite token EXPIRED"

Tokens expire daily at ~6 AM IST. Re-authenticate:

```bash
skopaq kite login-url
# ... login flow ...
skopaq kite session <new_request_token>
```

### "Session generation failed (403)"

- **Invalid request_token** — Request tokens are single-use and expire in minutes. Get a fresh one.
- **Wrong API secret** — Check `SKOPAQ_KITE_API_SECRET` in `.env`.
- **App not active** — Check your app status at developers.kite.trade.

### "API error 403: Forbidden"

- Token has expired (check `skopaq kite status`)
- IP not whitelisted (if your Kite app has IP restrictions)
- API subscription expired at developers.kite.trade

### "No quote available for SYMBOL"

In paper mode without a Kite token, the system falls back to yfinance. If yfinance also fails:

- Check internet connectivity
- The symbol might not exist on NSE (check spelling)
- yfinance may be rate-limited (wait and retry)

### "Cannot resolve instrument token"

The symbol doesn't exist in Kite's instrument master:

- Verify the symbol is listed on NSE: search on [kite.zerodha.com](https://kite.zerodha.com)
- Use the exact `tradingsymbol` (e.g., `RELIANCE`, not `RELIANCE.NS`)

### Paper trading works but live fails

- Verify `SKOPAQ_TRADING_MODE=live` in `.env`
- Verify Kite token is valid: `skopaq kite status`
- Check funds: log in to [kite.zerodha.com](https://kite.zerodha.com) and verify available margin
- Check if market is open (NSE: 9:15 AM - 3:30 PM IST, Mon-Fri)

---

## API Reference (Quick)

These are the Kite Connect REST API endpoints used by SkopaqTrader. Full documentation: [kite.trade/docs/connect](https://kite.trade/docs/connect/v3/).

### Authentication

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/session/token` | POST | Exchange `request_token` for `access_token` |

**Auth header for all other calls:**
```
Authorization: token {api_key}:{access_token}
X-Kite-Version: 3
```

### Market Data

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/quote?i=NSE:RELIANCE` | GET | Full quote (LTP, OHLC, depth, volume) |
| `/quote/ltp?i=NSE:RELIANCE` | GET | Last traded price only |
| `/instruments/NSE` | GET | Full instrument master (CSV, ~3MB) |
| `/instruments/historical/{token}/{interval}` | GET | OHLCV candles |

**Interval values:** `minute`, `5minute`, `15minute`, `30minute`, `60minute`, `day`, `week`, `month`

### Orders

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/orders/{variety}` | POST | Place order (variety: `regular`, `amo`, `co`, `iceberg`) |
| `/orders/{variety}/{order_id}` | PUT | Modify pending order |
| `/orders/{variety}/{order_id}` | DELETE | Cancel pending order |
| `/orders` | GET | All orders for the day |
| `/orders/{order_id}/trades` | GET | Trades for an order |
| `/trades` | GET | All trades for the day |

### Portfolio

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/portfolio/positions` | GET | Open positions (`net` + `day`) |
| `/portfolio/holdings` | GET | Delivery holdings |
| `/user/margins` | GET | Available funds per segment |
| `/user/profile` | GET | User profile |

### Rate Limits

- **General API:** 10 requests/second
- **Order API:** 10 requests/second (shared with general)
- **Historical data:** 3 requests/second

SkopaqTrader handles rate limiting automatically via token bucket (`skopaq/broker/rate_limiter.py`).

---

## Architecture: How Kite Integrates

```
┌──────────────────────────────────────────────────────────┐
│                     SkopaqTrader                          │
│                                                          │
│  .env: SKOPAQ_BROKER=kite                                │
│         │                                                │
│         v                                                │
│  ┌─────────────┐    ┌──────────────────┐                 │
│  │ SkopaqConfig │───>│ _create_live_    │                 │
│  │ broker="kite"│    │   client(config) │                 │
│  └─────────────┘    └────────┬─────────┘                 │
│                              │                           │
│                              v                           │
│                    ┌───────────────────┐                  │
│                    │ KiteConnectClient │                  │
│                    │  (kite_client.py) │                  │
│                    └────────┬──────────┘                  │
│                             │                            │
│         ┌───────────────────┼────────────────┐           │
│         │                   │                │           │
│         v                   v                v           │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ OrderRouter  │  │ MarketData   │  │ Position     │    │
│  │ (live/paper) │  │ Provider     │  │ Monitor      │    │
│  └──────┬───┬──┘  └──────┬───────┘  └──────┬───────┘    │
│         │   │             │                 │            │
│    live  │   │ paper       │ get_quote()     │ get_ltp()  │
│         v   v             v                 v            │
│   ┌──────┐ ┌──────────┐  ┌─────────────────────┐        │
│   │ Kite │ │ Paper    │  │ Kite API / yfinance  │        │
│   │ API  │ │ Engine   │  │ (auto-fallback)      │        │
│   └──────┘ └──────────┘  └─────────────────────┘        │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Key Files

| File | Purpose |
|------|---------|
| `skopaq/broker/kite_client.py` | Async REST client for Kite Connect API v3 |
| `skopaq/broker/kite_token_manager.py` | OAuth2 token lifecycle (login, store, expire) |
| `skopaq/broker/market_data.py` | Multi-source market data (Kite/yfinance/cache) |
| `skopaq/config.py` | `SKOPAQ_BROKER`, `SKOPAQ_KITE_API_KEY`, etc. |
| `skopaq/cli/main.py` | `skopaq kite` CLI commands |

### Differences from INDstocks

| Aspect | INDstocks | Kite Connect |
|--------|-----------|--------------|
| Auth header | `Authorization: TOKEN` | `Authorization: token api_key:access_token` |
| Symbol format | `scrip-codes=NSE_2885` | `i=NSE:RELIANCE` |
| Token lifetime | 24h rolling | Until ~6 AM IST |
| Token source | Dashboard copy-paste | OAuth2 browser login |
| Orders | `POST /order` + `algo_id` | `POST /orders/{variety}` |
| Product types | `INTRADAY`, `MARGIN`, `CNC` | `MIS`, `NRML`, `CNC` |
| Positions | Flat list | `{"net": [...], "day": [...]}` |
| Historical | Epoch ms input / epoch s output | Datetime strings / ISO timestamps |
| Brokerage | Varies | Rs. 20/order or 0.03% (whichever lower) |

---

## Cost Summary

| Item | Cost |
|------|------|
| Zerodha trading account | Free (no AMC for demat) |
| Kite Connect API subscription | Rs. 2,000/month |
| Historical data add-on | Rs. 2,000/month (optional, for backtesting) |
| Per-trade brokerage | Rs. 20/executed order or 0.03% |
| SkopaqTrader | Free (open source) |

> Check [zerodha.com/pricing](https://zerodha.com/pricing) and [developers.kite.trade](https://developers.kite.trade) for current pricing.

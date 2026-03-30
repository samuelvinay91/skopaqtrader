# Market Data Providers

SkopaqTrader's `MarketDataProvider` fetches real-time market data from multiple sources with automatic fallback. This means paper trading works out of the box — no broker token required.

## Fallback Chain

Sources are tried in order. The first one that returns valid data wins:

```
1. Broker API (Kite Connect / INDstocks)    ← best data, requires trading account
2. Angel One SmartAPI                        ← free, real-time, real bid/ask
3. Upstox API                                ← free, real-time, backup
4. yfinance                                  ← free, no setup, delayed data
5. Binance public API                        ← crypto only
6. Stale cache                               ← last known quote
```

## Data Quality Comparison

| Source | Real-time | Bid/Ask | Depth | Cost | Auth Required |
|--------|-----------|---------|-------|------|---------------|
| **Kite Connect** | Yes | Real | 5-level | Rs. 2,000/mo | Zerodha account + API subscription |
| **INDstocks** | Yes | Real | Limited | Paid | INDstocks account |
| **Angel One SmartAPI** | Yes | Real | 5-level | **Free** | Angel One demat (free to open) |
| **Upstox API** | Yes | Real | 5-level | **Free** | Upstox demat (free to open) |
| **yfinance** | No (15-20 min delay) | **Synthetic** (estimated ± 0.05%) | None | Free | None |
| **Binance** | Yes | Real | Full | Free | None (public endpoints) |

## Setup Guides

### Zero Config (yfinance only)

No setup needed. Just run:

```bash
skopaq trade RELIANCE
```

yfinance provides delayed data with synthetic bid/ask. Good enough for testing logic, but fills won't be realistic.

### Angel One SmartAPI (Recommended Free Option)

Best free option — real-time data with actual bid/ask from NSE.

1. **Open a free Angel One demat account** at [angelone.com](https://www.angelone.in/)
2. **Generate API key** at [smartapi.angelbroking.com](https://smartapi.angelbroking.com/)
   - Log in → My Apps → Create App
   - Note down: API Key
3. **Add credentials to `.env`:**

```bash
SKOPAQ_ANGELONE_API_KEY=your_api_key
SKOPAQ_ANGELONE_CLIENT_ID=your_client_id    # Angel One client code (e.g., A12345)
SKOPAQ_ANGELONE_PASSWORD=your_password
SKOPAQ_ANGELONE_TOTP_SECRET=your_totp_secret  # Optional: for automated TOTP
```

4. **That's it.** `MarketDataProvider` auto-detects the credentials and connects on first use.

> **Note:** Angel One login requires TOTP (2FA). If you set `SKOPAQ_ANGELONE_TOTP_SECRET`, the client generates TOTP codes automatically (requires `pyotp` package: `pip install pyotp`). Without it, you'll need to handle TOTP externally.

### Upstox API (Backup Free Option)

1. **Open a free Upstox demat account** at [upstox.com](https://upstox.com/)
2. **Create an API app** at [upstox.com/developer/apps](https://upstox.com/developer/apps)
   - Note down: API Key, API Secret
   - Set redirect URL: `http://127.0.0.1:5000/callback`
3. **Complete OAuth2 login** to get an access token:

```bash
# Open this URL in browser:
https://api.upstox.com/v2/login/authorization/dialog?client_id=YOUR_API_KEY&redirect_uri=http://127.0.0.1:5000/callback&response_type=code

# After login, you'll be redirected with ?code=xxx
# Exchange the code for an access_token via:
curl -X POST https://api.upstox.com/v2/login/authorization/token \
  -d "code=YOUR_CODE&client_id=YOUR_API_KEY&client_secret=YOUR_SECRET&redirect_uri=http://127.0.0.1:5000/callback&grant_type=authorization_code"
```

4. **Add to `.env`:**

```bash
SKOPAQ_UPSTOX_ACCESS_TOKEN=your_access_token
```

> **Note:** Upstox access tokens expire daily. Re-authenticate each morning before market open.

### Using Multiple Providers

You can configure all providers simultaneously. `MarketDataProvider` uses the first one that works:

```bash
# .env — configure all providers (best to worst)
SKOPAQ_BROKER=kite                    # Primary: Kite Connect
SKOPAQ_KITE_API_KEY=...

SKOPAQ_ANGELONE_API_KEY=...           # Fallback 1: Angel One (free)
SKOPAQ_ANGELONE_CLIENT_ID=...
SKOPAQ_ANGELONE_PASSWORD=...

SKOPAQ_UPSTOX_ACCESS_TOKEN=...        # Fallback 2: Upstox (free)

# yfinance always available as last resort (no config needed)
```

If Kite token expires mid-session, the system automatically falls back to Angel One, then Upstox, then yfinance — no interruption.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              MarketDataProvider                      │
│                                                     │
│  get_quote("RELIANCE")                              │
│       │                                             │
│       ├─ 1. _fetch_broker_quote()     → Kite/IND   │
│       │     (if broker client attached)             │
│       │                                             │
│       ├─ 2. _fetch_angelone_quote()   → Angel One   │
│       │     (auto-init from config)                 │
│       │                                             │
│       ├─ 3. _fetch_upstox_quote()     → Upstox     │
│       │     (auto-init from config)                 │
│       │                                             │
│       ├─ 4. _fetch_yfinance_quote()   → Yahoo       │
│       │     (always available)                      │
│       │                                             │
│       ├─ 5. _fetch_binance_quote()    → Binance    │
│       │     (crypto only)                           │
│       │                                             │
│       └─ 6. stale cache               → last known  │
│                                                     │
│  Result: Quote(symbol, ltp, bid, ask, ohlcv, ...)   │
└─────────────────────────────────────────────────────┘
```

## Key Files

| File | Purpose |
|------|---------|
| `skopaq/broker/market_data.py` | MarketDataProvider with fallback chain |
| `skopaq/broker/angelone_client.py` | Angel One SmartAPI client |
| `skopaq/broker/upstox_client.py` | Upstox API v2 client |
| `skopaq/broker/kite_client.py` | Kite Connect client |
| `skopaq/broker/client.py` | INDstocks client |
| `skopaq/config.py` | All provider credentials |

# Kite Connect Integration

SkopaqTrader integrates with Zerodha's [Kite Connect](https://kite.trade/) API for live market data, order execution, and portfolio management. The integration is in `skopaq/broker/kite_client.py`.

## Architecture

```
User Browser
      │
      │ GET /api/kite/login
      ▼
  FastAPI Server (skopaq/api/server.py)
      │
      │ Redirect to Zerodha
      ▼
  Zerodha Login Page
      │
      │ OAuth callback with request_token
      ▼
  GET /api/kite/callback?request_token=XXX
      │
      │ Exchange for access_token
      ▼
  KiteClient (skopaq/broker/kite_client.py)
      │
      │ Store token (memory + file + env var)
      ▼
  Ready for trading
```

## OAuth Flow

### Step 1: Login Redirect

The user visits `/api/kite/login`, which redirects to Zerodha's login page:

```python
@app.get("/api/kite/login")
async def kite_login():
    client = KiteClient(api_key=config.kite_api_key)
    return RedirectResponse(client.login_url)
```

### Step 2: Callback

After login, Zerodha redirects to `/api/kite/callback` with a `request_token`:

```python
@app.get("/api/kite/callback")
async def kite_callback(request_token: str, status: str):
    client = KiteClient(api_key=..., api_secret=...)
    session = client.generate_session(request_token)
    # Token stored automatically
```

### Step 3: Token Persistence

The access token is stored in three places for maximum reliability:

1. **Module-level cache** (`_access_token`) -- Fastest access
2. **File** (`/data/skopaq_kite_token.json` or `/tmp/...`) -- Survives module reloads
3. **Environment variable** (`SKOPAQ_KITE_ACCESS_TOKEN`) -- Subprocess access

Token retrieval priority:

```python
def get_access_token() -> str:
    # 1. Module cache (fastest)
    # 2. Persisted file (/data or /tmp)
    # 3. SKOPAQ_KITE_ACCESS_TOKEN env var
    # 4. SkopaqConfig (from .env)
```

!!! warning "Daily token expiry"
    Kite access tokens expire at the end of each trading day (around 6:00 AM IST next day). You must re-login daily. The Telegram bot sends a reminder at 09:00 IST.

## API Mapping

The `KiteClient` wraps the `kiteconnect` Python SDK to match the same interface as `INDstocksClient`:

| Method | Kite SDK Call | Returns |
|--------|--------------|---------|
| `get_quote(instrument)` | `kite.quote(instrument)` | `Quote` model |
| `get_positions()` | `kite.positions()["net"]` | `list[Position]` |
| `get_holdings()` | `kite.holdings()` | `list[Holding]` |
| `get_funds()` | `kite.margins("equity")` | `Funds` model |
| `get_orders()` | `kite.orders()` | `list[OrderResponse]` |
| `place_order(order)` | `kite.place_order(...)` | `ExecutionResult` |

Both `KiteClient` and `INDstocksClient` return the same Pydantic v2 models (`Quote`, `Position`, `Funds`, etc.) defined in `skopaq/broker/models.py`. This allows the `OrderRouter` to switch between brokers transparently.

## API Endpoints

The FastAPI server exposes these Kite-related endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/kite/login` | GET | Redirect to Zerodha login |
| `/api/kite/callback` | GET | Handle OAuth callback |
| `/api/kite/status` | GET | Check token validity |
| `/api/kite/token` | GET | Get current access token |
| `/api/kite/postback` | POST | Receive order postback webhooks |

## Configuration

Required environment variables:

```bash
# Kite Connect credentials (from developer console)
SKOPAQ_KITE_API_KEY=your_api_key
SKOPAQ_KITE_API_SECRET=your_api_secret

# Optional: pre-set access token (useful for testing)
SKOPAQ_KITE_ACCESS_TOKEN=your_token
```

## Instrument Format

Kite Connect uses the `EXCHANGE:TRADINGSYMBOL` format:

| Context | Format | Example |
|---------|--------|---------|
| Equities | `NSE:SYMBOL` | `NSE:RELIANCE` |
| Index | `NSE:NIFTY 50` | `NSE:NIFTY 50` |
| Options | `NFO:NIFTY2640124000CE` | `NFO:NIFTY2640124000CE` |

The MCP tools accept plain symbols (e.g., `RELIANCE`) and add the exchange prefix internally.

## Fallback Behavior

If Kite Connect is not available (no token), the system falls back to INDstocks for market data and the paper engine for portfolio/orders:

```python
kite = _get_kite()
if kite:
    quote = await kite.get_quote(f"NSE:{symbol}")
else:
    # Fall back to INDstocks
    async with INDstocksClient(config, token_mgr) as client:
        quote = await client.get_quote(scrip_code)
```

This means the system always works -- Kite just provides better data and live trading.

## Order Postback

Zerodha can send order status updates via webhook to `/api/kite/postback`. This enables real-time notification of order fills, rejections, and cancellations without polling.

Configure the postback URL in your Kite Connect app settings:

```
https://your-deployment.fly.dev/api/kite/postback
```

## File Reference

| File | Purpose |
|------|---------|
| `skopaq/broker/kite_client.py` | KiteClient class, token management |
| `skopaq/api/server.py` | OAuth endpoints (`/api/kite/*`) |
| `skopaq/broker/models.py` | Shared Pydantic models (Quote, Position, etc.) |
| `skopaq/mcp_server.py` | `_get_kite()` helper for MCP tools |

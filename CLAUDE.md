# CLAUDE.md — SkopaqTrader Project Context

This file provides context for AI coding agents working on the SkopaqTrader codebase.

## Project Overview

AI algorithmic trading platform for Indian equities. Built on vendored [TradingAgents v0.2.0](https://github.com/TauricResearch/TradingAgents) (Apache 2.0) with a custom `skopaq/` layer for multi-broker integration (INDstocks + Kite Connect), multi-model LLM tiering, and an autonomous execution pipeline.

## Architecture

Two codebases in one repo:

- **`tradingagents/`** — Vendored upstream. Multi-agent LangGraph pipeline: 4 analysts → bull/bear researchers → risk debate → trader decision. Modifications are surgical and tracked in `UPSTREAM_CHANGES.md`.
- **`skopaq/`** — Custom extensions: broker client, execution pipeline, CLI, config, LLM tiering, scanner, risk management, memory, daemon.

### Key Flow

```
CLI/API → SkopaqTradingGraph → [upstream LangGraph agents] → TradeSignal
  → SafetyChecker → PositionSizer → OrderRouter → Broker(INDstocks|Kite)/Paper
  → PositionMonitor(MarketDataProvider) → SellAnalyst → exit
```

### Daemon Flow (autonomous)

```
PRE_OPEN → SCANNING → ANALYZING → TRADING → MONITORING → CLOSING → REPORTING
```

The daemon (`skopaq/execution/daemon.py`) is a finite state machine that composes all subsystems into a single unattended trading session.

## Common Commands

```bash
# Run unit tests (466 tests, no API keys needed)
python3 -m pytest tests/unit/ -x -q

# Run a specific test file
python3 -m pytest tests/unit/execution/test_daemon.py -v

# Run integration tests (requires .env with real keys)
python3 -m pytest tests/integration/ -v -m integration

# CLI commands
skopaq status              # Health check
skopaq analyze RELIANCE    # Analysis only
skopaq trade RELIANCE      # Analysis + execution (paper default)
skopaq scan                # Scanner cycle
skopaq daemon --once --paper  # Full autonomous session
skopaq monitor             # Monitor existing positions
skopaq serve               # FastAPI server

# Kite Connect (Zerodha) broker
skopaq kite login-url      # Print OAuth login URL
skopaq kite session <tok>  # Exchange request_token for access_token
skopaq kite set-token <tok># Store access_token directly
skopaq kite status         # Check Kite token health
skopaq kite clear          # Delete stored Kite token
```

## Configuration

- **`SkopaqConfig`** in `skopaq/config.py` — Pydantic Settings with `env_prefix="SKOPAQ_"`
- **`.env`** file at repo root (gitignored) — all secrets live here
- **`.env.example`** — template with all configurable keys and placeholders
- **Env bridging** — `skopaq/llm/env_bridge.py` copies `SKOPAQ_*` → standard env vars (e.g., `SKOPAQ_GOOGLE_API_KEY` → `GOOGLE_API_KEY`) so upstream TradingAgents works without modification

## LLM Setup

| Role | Model | Provider |
|------|-------|----------|
| Most analyst/researcher roles | Gemini 3 Flash Preview | Google |
| Social Analyst | Grok 3 Mini | OpenRouter (`x-ai/grok-3-mini`) |
| News Analyst | Gemini 3 Flash | Google |
| Research Manager, Risk Manager | Claude Opus 4.6 | Anthropic |
| Scanner screeners | Gemini + Grok + Perplexity Sonar | Concurrent |
| Sell Analyst | Gemini 3 Flash | Google |

**Critical:** Perplexity Sonar does NOT support tool calling — it can only be used for scanner plain prompts, never as a LangGraph agent.

**Critical:** Gemini 3 returns `response.content` as a list of dicts, not a string. Always use `skopaq.llm.extract_text()` to normalize.

## Broker Selection

Set `SKOPAQ_BROKER=indstocks` (default) or `SKOPAQ_BROKER=kite` to choose the broker. The `OrderRouter` dispatches to either client via a `BrokerClient` protocol. Paper mode works without any broker credentials — the `MarketDataProvider` falls back to yfinance.

## INDstocks API

- ALL market data endpoints use `scrip-codes=NSE_2885` format (NOT `symbols=NSE:RELIANCE`)
- Auth header: `Authorization: TOKEN` (no "Bearer" prefix)
- Historical endpoint: input timestamps in **milliseconds**, response `ts` in **seconds**
- Candle objects: `{"ts":, "o":, "h":, "l":, "c":, "v":}`
- Quote fields: `live_price`, `day_open`, `day_high`, `day_low`, `prev_close`
- Always refer to `docs/indstocks_api.md` for endpoint reference — do not assume

## Kite Connect API

- Auth header: `Authorization: token api_key:access_token`
- Quote endpoint: `GET /quote?i=NSE:RELIANCE` (instrument key format `EXCHANGE:SYMBOL`)
- Orders: `POST /orders/{variety}` where variety = `regular`, `amo`, `co`, `iceberg`
- Product types: `CNC` (delivery), `MIS` (intraday), `NRML` (F&O)
- Positions: `GET /portfolio/positions` returns `{"net": [...], "day": [...]}`
- Historical: `GET /instruments/historical/{token}/{interval}` with datetime strings
- Instruments: `GET /instruments/NSE` returns CSV with `instrument_token`, `tradingsymbol`
- Token lifecycle: OAuth2 flow → `access_token` valid until ~6:00 AM IST next day
- CLI: `skopaq kite login-url`, `skopaq kite session <request_token>`, `skopaq kite status`

## MarketDataProvider

`skopaq/broker/market_data.py` — unified async market data layer used by paper engine and position monitor. Tries sources in priority order:

1. **Broker API** (INDstocks or Kite) — best data, real bid/ask
2. **yfinance** (no credentials) — free fallback for any symbol
3. **Binance public API** — for crypto (no auth needed)
4. **Stale cache** — last resort, returns last known quote

Paper mode auto-refreshes quotes before every fill via `PaperEngine.execute_order_async()`.

## File Organization

```
skopaq/
├── agents/          # Sell analyst (AI exit decisions)
├── api/             # FastAPI backend
├── broker/          # INDstocks + Kite Connect + Binance + paper engine + market data provider
├── cli/             # Typer CLI (main.py = all commands, display.py = Rich output)
├── db/              # Supabase client + repositories
├── execution/       # Executor, safety checker, order router, daemon, position monitor
├── graph/           # SkopaqTradingGraph (wraps upstream)
├── llm/             # Model tiering, env bridge, semantic cache (LangCache)
├── memory/          # BM25-indexed agent memory (Supabase-backed)
├── risk/            # ATR sizing, regime detection, drawdown tracker, calendar
├── scanner/         # Multi-model scanner engine + watchlist + screen models
├── config.py        # SkopaqConfig (pydantic-settings)
└── constants.py     # SafetyRules (immutable) + daemon variants
```

## Testing Patterns

- **Unit tests** (`tests/unit/`): Mock all external dependencies. No API keys needed.
- **Integration tests** (`tests/integration/`): Real API calls. Require `.env` with valid keys.
- **Fixtures**: Common config mocks in test files. `conftest.py` at `tests/` root.
- **Async tests**: Use `@pytest.mark.asyncio` + `AsyncMock` for async methods.
- **Patch targets**: When a function is locally imported inside a method body (common in `daemon.py`), patch at the **source module**, not the importing module. Example: `patch("skopaq.cli.main._run_scan")` not `patch("skopaq.execution.daemon._run_scan")`.

## Key Conventions

1. **Safety rules are immutable** — `SafetyRules` in `constants.py` cannot be overridden at runtime. The `SafetyChecker` enforces them before every order.
2. **Paper mode is default** — All CLI commands default to paper trading. Paper mode works without broker credentials (yfinance fallback). Live mode requires explicit `--live` or `SKOPAQ_TRADING_MODE=live` + confirmation prompt.
7. **MarketDataProvider for paper mode** — The `PaperEngine` uses `MarketDataProvider` to auto-refresh quotes before fills. Use `execute_order_async()` (not `execute_order()`) when a provider is attached. The `PositionMonitor` uses `MarketDataProvider` for LTP polling (not a broker client directly).
3. **Upstream modifications are minimal** — Changes to `tradingagents/` must be documented in `UPSTREAM_CHANGES.md` with backward-compatibility notes.
4. **No secrets in code** — All credentials come from environment variables. Never commit `.env`, token files, or API keys.
5. **Pydantic v2 models** — Broker models in `skopaq/broker/models.py` use Pydantic v2. Use attribute access (`model.field`), not dict access (`model["field"]` or `model.get("field")`).
6. **Rich output** — All CLI display uses Rich tables/panels via `skopaq/cli/display.py` and `skopaq/cli/theme.py`.

## Common Gotchas

- **Gemini content format**: `response.content` returns `[{"type": "text", "text": "..."}]` not a plain string. Use `extract_text()`.
- **INDstocks timestamps**: Historical API wants milliseconds, returns seconds. Off by 1000x is a common bug.
- **yfinance suffixes**: LLM agents generate `RELIANCE.NS` (Yahoo Finance convention). The routing layer adds/strips suffixes automatically, but new data flows must handle this.
- **Local imports in daemon.py**: Many imports are inside method bodies to avoid circular imports. This affects mock patch targets in tests (see Testing Patterns above).
- **Stop event propagation**: The daemon's `stop_event` must be checked before every major operation, not just inside delay waits.
- **Broker client type**: `OrderRouter` uses a `BrokerClient` protocol — both `INDstocksClient` and `KiteConnectClient` satisfy it. Don't use `isinstance` checks; use `config.broker` to dispatch.
- **Kite token expiry**: Kite tokens expire at ~6:00 AM IST daily (not rolling 24h like INDstocks). The `KiteTokenManager` calculates expiry to next 6 AM.
- **PositionMonitor no longer takes a broker client** — it takes a `MarketDataProvider` instead. The old `client` parameter is ignored (backward compat).

## Deployment

- **Railway API** — `railway.toml` — FastAPI server (always running)
- **Railway Daemon** — `railway-daemon.toml` — Cron job at 09:10 IST weekdays
- **Vercel** — `frontend/` — Next.js dashboard
- **Supabase** — PostgreSQL + auth + agent memory
- **Upstash** — Redis for semantic LLM cache (LangCache)
- **Cloudflare Tunnel** — Static IP for INDstocks API whitelist

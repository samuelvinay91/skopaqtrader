<div align="center">

<img src="assets/hero_banner.png" alt="SkopaqTrader AI Platform" style="max-width: 100%; height: auto; object-fit: contain;" />

# SkopaqTrader

**An open-source AI algorithmic trading platform for Indian equities**

Built on [TradingAgents](https://github.com/TauricResearch/TradingAgents) (Apache 2.0) by TauricResearch

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab?logo=python&logoColor=white)](https://python.org)
[![Built with LangGraph](https://img.shields.io/badge/Built_with-LangGraph-grey)](https://langchain-ai.github.io/langgraph/)

</div>

> [!CAUTION]
> **IMPORTANT LEGAL DISCLAIMER**
>
> This software is provided **strictly for educational and research purposes only**. It is **NOT** financial advice, investment advice, or trading advice of any kind.
>
> - **No guarantees of profit.** Algorithmic trading involves substantial risk of financial loss. Past performance does not guarantee future results.
> - **You are solely responsible** for any trades executed using this software, whether in paper or live mode.
> - **The authors and contributors are not** registered investment advisors, broker-dealers, or financial planners under SEBI, SEC, or any regulatory body.
> - **Use at your own risk.** By using this software, you acknowledge that you understand the risks of automated trading and accept full responsibility for all outcomes.
>
> *If you need financial advice, consult a SEBI-registered investment advisor.*

---

## Overview

SkopaqTrader extends the [TradingAgents](https://github.com/TauricResearch/TradingAgents) multi-agent LLM framework with Indian equity market support, multi-model tiering, broker integration, and an experience-driven execution pipeline.

**Key capabilities:**

- **Post-Trade Reflection Loop** — Reflection node analyzes past trades and injects history into the analyst context, enabling the system to incorporate lessons from wins and losses over time.
- **Persistent Agent Memory** — BM25-indexed memory store backed by Supabase for long-term strategic recall across all agent roles.
- **Multi-agent analysis** — Analyst team (market, news, social, fundamentals), bull/bear researchers, risk manager, and trader agent collaborate via LangGraph.
- **Multi-model tiering** — Per-role LLM assignment across multiple providers for cost optimization and capability matching. See the [model tiering table](#multi-model-tiering) below for details.
- **Semantic LLM Caching** — Built-in Redis LangCache provides significant speedup (up to ~45x in our benchmarks) on repeated queries and reduces API costs, with automatic semantic invalidation on memory updates.
- **Advanced Risk Management** — Features ATR-based position sizing, India VIX/NIFTY SMA market regime detection, NSE event calendar handling (F&O expiry, RBI policy), and sector concentration limits.
- **Live Algo Trading** — Integrates with INDstocks and Kite Connect (Zerodha) broker APIs for execution on Indian equities (NSE/BSE). Start in paper mode, graduate to live when ready.
- **Live-Data Paper Trading** — Paper mode uses real market data from any source (broker API, yfinance, Binance public) with automatic fallback. No broker credentials required to paper trade.
- **Confidence-Scored Position Sizing** — The Risk Manager evaluates trades with strict confidence scores (50-100%). Position sizes are dynamically scaled based on this AI confidence level.
- **Parallel Scanner Engine** — 30-second multi-model screening cycle on the NIFTY 50 watchlist, wired directly to INDstocks batch quotes and 3 LLM screeners (Gemini, Grok, Perplexity) running concurrently.
- **Safety-First Execution** — Immutable position limits, persistent drawdown tracking, daily loss circuit breakers, and small-account exemptions.
- **Autonomous Trading Daemon** — Full session orchestrator: PRE_OPEN → SCANNING → ANALYZING → TRADING → MONITORING → CLOSING → REPORTING. Runs unattended on a cron schedule with graceful SIGTERM handling and tighter safety rules.
- **Three-Tier Position Monitor** — Hard stop-loss, AI sell analyst, and EOD safety net with optional trailing stops and configurable poll intervals.
- **Min Profit Gate** — Two-layer protection against brokerage-eating-profit: prompt guidance to the sell analyst LLM + hard override in the monitor that blocks sells when net profit (after estimated brokerage) is below threshold.
- **Crypto Support** — On-chain (Blockchair), DeFi/tokenomics (DeFiLlama/CoinGecko), and funding rate (Binance Futures) analysts activate when `asset_class=crypto`.
- **Blockchain Infrastructure** — Live Binance trading, WebSocket real-time feeds, gas oracles (ETH/Polygon/Arbitrum/Optimism), whale transaction alerts, and multi-exchange abstraction layer.

<img src="assets/dashboard.png" alt="Skopaq Dashboard" style="max-width: 100%; height: auto;" />
*Dashboard for monitoring agent workflows, market scanning, and trade execution.*

- **Paper → Live pipeline** — Start paper, graduate to live when ready

> **Reminder:** See the [full disclaimer](#important-legal-disclaimer) at the top. This is a research tool, not a trading recommendation system.

## 🏗️ Technical Architecture

```mermaid
graph TD
    classDef interface fill:#3b82f6,stroke:#2563eb,stroke-width:2px,color:#fff
    classDef core fill:#8b5cf6,stroke:#7c3aed,stroke-width:2px,color:#fff
    classDef agent fill:#10b981,stroke:#059669,stroke-width:2px,color:#fff
    classDef execution fill:#f59e0b,stroke:#d97706,stroke-width:2px,color:#fff
    classDef external fill:#475569,stroke:#334155,stroke-width:2px,color:#fff

    subgraph UI["User Interfaces"]
        CLI["CLI Interface"]:::interface
        API["FastAPI Backend"]:::interface
        Dashboard["Next.js Dashboard"]:::interface
    end

    subgraph CoreSystem["SkopaqTrader Core"]
        Orchestrator["SkopaqTradingGraph<br/>System Orchestrator"]:::core
        DataAgents["Data Analysts<br/>Market / News / Social"]:::agent
        ResearchAgents["Researchers<br/>Bull / Bear / Debate"]:::agent
        RiskAgent["Risk Manager<br/>Evaluation"]:::agent
        TraderAgent["Trader Agent<br/>Decision"]:::agent
    end

    subgraph Exec["Execution Pipeline"]
        Safety["Safety Checker<br/>Circuit Breakers"]:::execution
        Router["Order Router<br/>Live / Paper"]:::execution
    end

    subgraph Infra["Infrastructure"]
        Broker["INDstocks / Kite Connect<br/>NSE / BSE Trading"]:::external
        Supabase["Supabase DB<br/>State, History, Auth"]:::external
        Redis["Redis LangCache<br/>Semantic LLM Caching"]:::external
    end

    CLI --> Orchestrator
    API --> Orchestrator
    Dashboard --> Orchestrator
    Orchestrator --> DataAgents
    DataAgents --> ResearchAgents
    ResearchAgents --> RiskAgent
    RiskAgent -- "Confidence %" --> TraderAgent
    TraderAgent --> Safety
    Safety --> Router
    Router --> Broker
    Orchestrator -.-> Supabase
    Orchestrator -.-> Redis
    Router -. "Trade Result" .-> Orchestrator
    Orchestrator -. "Reflection" .-> DataAgents
```

*High-level overview of the SkopaqTrader architecture, connecting the user interfaces to the multi-agent AI team and the broker execution engine.*

### 🤖 AI Agent Workflow

<img src="assets/agent_network.png" alt="Concept: AI Agent Neural Network" style="max-width: 100%; height: auto;" />
<br/>
<sub>*Conceptual representation of the high-speed data flow between the AI Analyst agents, debate researchers, and the core routing system.*</sub>

```mermaid
sequenceDiagram
    participant User as User Input
    participant Orch as Orchestrator
    participant Analysts as Analyst Agents
    participant Research as Researchers
    participant Risk as Risk Manager
    participant Trader as Trader Agent
    participant Broker as Broker (INDstocks / Kite)

    User->>Orch: Request Analysis (e.g. RELIANCE)
    Orch->>Analysts: Gather Market, News, Social Data
    Note over Analysts: Multiple LLM providers<br/>Accelerated by Redis LangCache
    Analysts-->>Orch: Formatted Data and Sentiment
    Orch->>Research: Generate Bull and Bear Thesis
    Note over Research: Deep reasoning LLM
    Research-->>Orch: Competing Arguments and Debate
    Orch->>Trader: Propose Trading Strategy
    Trader-->>Orch: Draft Order (Buy/Sell/Hold)
    Orch->>Risk: Evaluate Draft against Safety Limits
    Risk-->>Orch: Assign Confidence Score (50-100%)
    alt Order Approved
        Orch->>Broker: Execute Live/Paper Trade
        Broker-->>Orch: Delivery and Price Confirmation
        Orch->>Orch: Reflection Node (Self-Evolution)
        Orch-->>User: Trade Success and Report
    else Order Rejected
        Orch-->>User: Trade Blocked (Safety Protocol)
    end
```

*The step-by-step collaborative workflow of our AI agent team, from data gathering to safe execution.*

### 🚀 Usage Lifecycle (For Beginners)

```mermaid
flowchart LR
    classDef step fill:#f3f4f6,stroke:#9ca3af,stroke-width:2px,color:#1f2937
    classDef highlight fill:#dbeafe,stroke:#3b82f6,stroke-width:2px,color:#1e3a8a

    S1["1. Pick a Stock<br/>or run the Screener"]:::step
    S2["2. AI Team Analyzes<br/>News, Trends, Fundamentals"]:::step
    S3["3. AI Debate and Decision<br/>Bull vs Bear Arguments"]:::step
    S4["4. Risk and Confidence Check<br/>Score validates position size"]:::step
    S5["5. Execute Trade<br/>Paper or Live via Broker"]:::highlight
    S6["6. Reflect and Learn<br/>Lessons feed future trades"]:::step

    S1 --> S2 --> S3 --> S4 --> S5 -.-> S6
    S6 -. "Feeds next trade" .-> S2
```

*A simple mental model of how SkopaqTrader operates, making complex algorithmic trading easy to understand.*

### 🔍 Deep-Dive: Scanner Engine & Advanced Risk

<img src="assets/data_scanner.png" alt="Concept: Real-Time Market Scanner" style="max-width: 100%; height: auto;" />
<br/>
<sub>*Conceptual UI of the SkopaqTrader scanner engine processing live NIFTY 50 metrics, sentiment scores, and confidence data.*</sub>

The real power of SkopaqTrader lies in its parallel scanner and dynamic risk management logic. When running `skopaq scan`, the system doesn't rely on just one LLM or simple heuristics. It queries multiple models simultaneously while injecting Indian market regime rules.

```mermaid
flowchart TD
    classDef trigger fill:#10b981,stroke:#047857,color:#fff
    classDef data fill:#3b82f6,stroke:#2563eb,color:#fff
    classDef llm fill:#8b5cf6,stroke:#7c3aed,color:#fff
    classDef check fill:#f59e0b,stroke:#d97706,color:#fff
    classDef memory fill:#475569,stroke:#334155,color:#fff

    Start(("skopaq scan<br/>NIFTY 50")):::trigger
    INDapi["Broker API Batch Quote<br/>(INDstocks / Kite / yfinance)"]:::data
    CacheCheck{"Redis LangCache<br/>Semantic Check"}:::check
    CachedData["Return Cached Inference"]:::llm

    Start --> INDapi --> CacheCheck
    CacheCheck -- "Hit" --> CachedData
    CacheCheck -- "Miss" --> Gemini

    subgraph Screeners["Parallel Screening Cluster"]
        Gemini["Gemini 3 Flash<br/>Tech / Fundamentals"]:::llm
        Grok["Grok 3 Mini<br/>Social Sentiment"]:::llm
        Perplexity["Perplexity Sonar<br/>Web / News Context"]:::llm
    end

    CacheCheck -- "Miss" --> Grok
    CacheCheck -- "Miss" --> Perplexity

    Gemini --> Synthesis["Risk Management<br/>Strategy Synthesis"]:::check
    Grok --> Synthesis
    Perplexity --> Synthesis

    subgraph RiskEval["Advanced Risk Evaluator"]
        Regime["Detect Regime<br/>VIX / NIFTY SMA"]:::check
        Events["Calendar Checks<br/>RBI / F&O Expiry"]:::check
        Size["ATR Position Sizing<br/>Concentration Limits"]:::check
    end

    Synthesis --> Regime
    Synthesis --> Events
    Regime --> Size
    Events --> Size
    Size --> Confidence{"Confidence Score<br/>above 50% ?"}:::check

    Confidence -- "Yes" --> EmitTrade("Emit Trade Execution"):::trigger
    Confidence -- "No" --> Drop("Discard Candidate"):::memory

    EmitTrade -.-> SupaDB["Supabase DB<br/>Record Trade and Memory"]:::memory
```

### Multi-Model Tiering

| Agent Role | Primary Model | Fallback |
|------------|---------------|----------|
| Market / Fundamentals Analyst | Gemini 3 Flash | — |
| Social Analyst | Grok 3 Mini (via OpenRouter) | Gemini 3 Flash |
| News Analyst | Gemini 3 Flash | — |
| Research Manager | Claude Opus 4.6 | Gemini 3 Flash |
| Risk Manager | Claude Opus 4.6 | Gemini 3 Flash |
| Bull / Bear / Debate Researchers | Gemini 3 Flash | — |
| Trader | Gemini 3 Flash | — |
| Sell Analyst | Gemini 3 Flash | — |
| Scanner Screeners | Gemini 3 Flash, Grok 3 Mini, Perplexity Sonar | (concurrent) |

> **Note:** Perplexity Sonar is used only in the scanner (plain prompts). It does not support tool calling, so it cannot serve as an analyst in the LangGraph agent pipeline.

### Blockchain Infrastructure

SkopaqTrader includes comprehensive blockchain infrastructure for crypto trading:

| Feature | Module | Description |
|---------|--------|-------------|
| **Kite Connect** | `skopaq/broker/kite_client.py` | Zerodha Kite Connect REST API v3 for NSE/BSE trading |
| **Live Trading** | `skopaq/broker/binance_auth.py` | Authenticated Binance API for spot trading with API keys |
| **Real-Time Feeds** | `skopaq/broker/binance_ws.py` | WebSocket streams for ticker, trades, order book, klines |
| **Gas Oracle** | `skopaq/blockchain/gas.py` | ETH, Polygon, Arbitrum, Optimism gas prices + tx cost estimates |
| **Whale Alerts** | `skopaq/blockchain/whales.py` | Large transaction monitoring for BTC, ETH, SOL |
| **Multi-Exchange** | `skopaq/broker/exchange.py` | Unified abstraction layer (Binance, Coinbase, Kraken) |

```python
# Live Binance trading
from skopaq.broker import BinanceAuthClient

async with BinanceAuthClient(api_key="...", api_secret="...") as client:
    await client.place_order("BTCUSDT", "BUY", 0.001, 50000.0)

# Real-time price via WebSocket
from skopaq.broker import BinanceWS

ws = BinanceWS()
async for ticker in ws.ticker_stream("BTCUSDT"):
    print(f"BTC: ${ticker.price}")

# Gas oracle
from skopaq.blockchain import get_gas_price, get_gas_estimate

gas = await get_gas_price("ETH")
estimate = await get_gas_estimate("ETH", "USDT transfer")

# Whale alerts
from skopaq.blockchain import check_whale_alerts

alerts = await check_whale_alerts("ETH", min_value_usd=100000)
```

## Installation

### Prerequisites

- Python 3.11+
- API keys for at least one LLM provider (Google Gemini recommended as minimum)

### Setup

```bash
git clone https://github.com/bvkio/skopaqtrader.git
cd skopaqtrader

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Required API Keys

At minimum, set `GOOGLE_API_KEY` for Gemini 3 Flash (used as default/fallback for all roles).

For full multi-model tiering:

```bash
GOOGLE_API_KEY=...          # Gemini 3 Flash (all analyst roles)
ANTHROPIC_API_KEY=...       # Claude Opus 4.6 (research/risk manager)
OPENROUTER_API_KEY=...      # Grok + Perplexity Sonar (social + news)
```

See [`.env.example`](.env.example) for all configuration options.

## Usage

> [!WARNING]
> All trading commands (live or paper) are **at your own risk**. The AI agents may produce incorrect signals. Always verify positions manually and never risk capital you cannot afford to lose.

### CLI

```bash
# System health check
skopaq status

# Analyze a stock (no execution)
skopaq analyze RELIANCE
skopaq analyze TATAMOTORS --date 2026-02-28

# Trade a specific stock (full lifecycle: analyze + trade + monitor + close)
skopaq trade RELIANCE

# Auto-discover and trade (scan NIFTY 50 → pick best → trade → monitor)
skopaq trade                           # Best single pick
skopaq trade --top 3                   # Trade top 3 candidates
skopaq trade --watchlist "RELIANCE,TCS,INFY"  # Scan only these symbols
skopaq trade --no-monitor              # Skip position monitoring

# Run scanner cycle (no execution)
skopaq scan --max-candidates 5

# Autonomous daemon (full session: scan → trade → monitor → close)
# WARNING: The daemon trades autonomously. Use paper mode until you are confident.
skopaq daemon --once --paper           # Single paper session, run immediately
skopaq daemon --dry-run                # Scanner only, print candidates, exit
skopaq daemon --once --max-trades 1    # Live mode, 1 trade max (requires confirmation)

# Position monitor (attach to existing open positions)
skopaq monitor                         # Monitor all open positions until EOD

# Start API server
skopaq serve --port 8000

# Token management (INDstocks broker)
skopaq token set <your-token>
skopaq token status

# Kite Connect (Zerodha) broker
skopaq kite login-url                  # Get OAuth login URL
skopaq kite session <request-token>    # Exchange for access token
skopaq kite status                     # Check Kite token health
```

### Broker Selection

Set `SKOPAQ_BROKER` in `.env` to choose your broker:

```bash
SKOPAQ_BROKER=indstocks   # INDstocks (default)
SKOPAQ_BROKER=kite        # Kite Connect (Zerodha)
```

Paper trading works **without any broker credentials** — the `MarketDataProvider` automatically falls back to yfinance for market data.

### Python API

```python
from skopaq.config import SkopaqConfig
from skopaq.graph.skopaq_graph import SkopaqTradingGraph

config = SkopaqConfig()
graph = SkopaqTradingGraph(config)

# Analysis only
result = await graph.analyze("RELIANCE", "2026-03-01")
print(result.signal)

# Analysis + execution
result = await graph.analyze_and_execute("RELIANCE", "2026-03-01")
print(result.execution)
```

### Upstream TradingAgents (Direct)

The vendored upstream is fully functional:

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())
_, decision = ta.propagate("NVDA", "2026-01-15")
print(decision)
```

## Project Structure

```
skopaqtrader/
├── tradingagents/              # Vendored upstream (TradingAgents v0.2.0)
│   ├── agents/                 # Analyst, researcher, trader, risk agents
│   │   ├── analysts/           # Market, news, social, fundamentals + crypto analysts
│   │   ├── researchers/        # Bull/bear researchers
│   │   ├── managers/           # Research + risk managers
│   │   ├── risk_mgmt/          # Aggressive/conservative/neutral debators
│   │   └── trader/             # Final trade decision agent
│   ├── graph/                  # LangGraph orchestration + reflection
│   ├── dataflows/              # Data vendors (yfinance, INDstocks, crypto APIs)
│   └── llm_clients/            # LLM factory (OpenAI, Google, Anthropic, etc.)
│
├── skopaq/                     # SkopaqTrader extensions
│   ├── agents/                 # Sell analyst (AI exit decisions)
│   ├── api/                    # FastAPI backend server
│   ├── blockchain/             # Gas oracle, whale alerts
│   ├── broker/                 # INDstocks + Kite Connect + Binance + paper engine + market data provider
│   ├── cli/                    # Typer CLI (analyze, trade, scan, daemon, monitor)
│   ├── db/                     # Supabase client + repositories
│   ├── execution/              # Executor, safety checker, order router, daemon, monitor
│   ├── graph/                  # SkopaqTradingGraph (upstream wrapper)
│   ├── llm/                    # Multi-model tiering, env bridge, semantic cache
│   ├── memory/                 # BM25-indexed agent memory (Supabase-backed)
│   ├── risk/                   # ATR sizing, regime detection, drawdown, calendar
│   ├── scanner/                # Multi-model market scanner engine
│   ├── config.py               # Pydantic Settings (env_prefix="SKOPAQ_")
│   └── constants.py            # Immutable safety rules + daemon variants
│
├── frontend/                   # Next.js dashboard (Vercel)
├── supabase/                   # Database migrations
├── docker/                     # Dockerfile for Railway
├── tests/                      # 466 unit + integration tests
│   ├── unit/                   # Fast tests (no API keys needed)
│   └── integration/            # Real API calls (requires .env)
│
├── CLAUDE.md                   # AI agent project context
├── UPSTREAM_CHANGES.md         # All modifications to vendored code (34 changes)
├── CONTRIBUTING.md             # Contribution guidelines
├── pyproject.toml              # Python project config
├── railway.toml                # Railway API server config
├── railway-daemon.toml         # Railway daemon cron config
└── LICENSE                     # Apache 2.0
```

## Security

- **No secrets in the repository.** All API keys, tokens, and credentials are loaded from environment variables via `.env` (gitignored). See [`.env.example`](.env.example) for the full list of configurable keys.
- **Broker tokens** are encrypted at rest in `~/.skopaq/` (INDstocks: `token.enc`, Kite: `kite_token.enc`) using Fernet symmetric encryption and validated on every daemon session start.
- **Immutable safety rules** in `skopaq/constants.py` enforce position limits, order value caps, and rate limits that cannot be overridden at runtime.
- **Daemon safety variants** apply tighter limits for unattended operation (fewer positions, lower order caps, slower pace).
- **Live trading double-gate** — the `trade` and `daemon` CLI commands require an explicit confirmation prompt before executing real orders.

If you discover a security issue, please report it privately rather than opening a public issue.

## Testing

The test suite contains **466 unit tests** (no API keys needed) plus integration tests for real broker/LLM calls.

```bash
# Unit tests — fast, no external dependencies
python -m pytest tests/unit/ -v

# Integration tests (requires .env with real API keys)
python -m pytest tests/integration/ -v -m integration

# All tests with coverage
python -m pytest --cov=skopaq --cov=tradingagents -v
```

## Deployment

> [!WARNING]
> Deploying autonomous trading to a cloud server means orders will execute **without human supervision**. Start with paper mode, set conservative limits, and monitor logs daily. You are fully responsible for any trades placed by the daemon.

| Service | Config | Purpose |
|---------|--------|---------|
| **Railway** (API) | [`railway.toml`](railway.toml) | FastAPI backend server |
| **Railway** (Daemon) | [`railway-daemon.toml`](railway-daemon.toml) | Autonomous trading cron (09:10 IST, weekdays) |
| **Vercel** | `frontend/` | Next.js dashboard |
| **Supabase** | `supabase/` | PostgreSQL + Auth + agent memory |
| **Upstash** | — | Serverless Redis (semantic LLM cache) |
| **Cloudflare Tunnel** | — | Static IP for INDstocks API whitelist |

See [`docker/Dockerfile`](docker/Dockerfile) for the shared container image used by both Railway services.

## Upstream Modifications

All 34 changes to the vendored `tradingagents/` directory are documented in [`UPSTREAM_CHANGES.md`](UPSTREAM_CHANGES.md).

**Modification philosophy:** Minimal, surgical changes. The upstream graph runs as a black box via `propagate()`. Skopaq wraps it with execution, safety, and multi-model tiering.

**Categories of modifications:**

- **Multi-model tiering** — `llm_map` support in `graph/setup.py` and `trading_graph.py`
- **INDstocks data vendor** — New `dataflows/indstocks.py` + registration in `interface.py`
- **Parallel analyst execution** — State reducers in `agent_states.py`, fan-out wiring in `setup.py`
- **Crypto analyst agents** — 7 new files (on-chain, DeFi, funding) + 9 modified debate consumers
- **Confidence scoring** — Risk manager prompt addition for structured confidence output
- **Bugfixes** — yfinance symbol suffix handling, comma-separated indicator splitting, `.NS`/`.BO` stripping

**Diff command:** `git diff upstream-v0.2.0..HEAD -- tradingagents/`

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

**Quick start:**

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Write tests for your changes
4. Ensure all tests pass (`python -m pytest tests/unit/ -v`)
5. Submit a pull request

## Citation

SkopaqTrader is built on the TradingAgents framework. Please reference the original work:

```bibtex
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework},
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138},
}
```

## Trademarks

All product names, logos, and brands mentioned in this project are property of their respective owners. Their use here does not imply endorsement, sponsorship, or affiliation.

- **Gemini** is a trademark of Google LLC.
- **Claude** is a trademark of Anthropic, PBC.
- **Grok** is a trademark of xAI Corp.
- **Perplexity** is a trademark of Perplexity AI, Inc.
- **LangGraph** and **LangChain** are trademarks of LangChain, Inc.
- **NIFTY** and **NIFTY 50** are registered trademarks of NSE Indices Limited.
- **NSE** is a trademark of National Stock Exchange of India Limited.
- **BSE** is a trademark of BSE Limited.
- **INDstocks** is a trademark of its respective owner.
- **Zerodha** and **Kite Connect** are trademarks of Zerodha Broking Ltd.
- **Supabase**, **Vercel**, **Railway**, **Upstash**, **Cloudflare**, and **OpenRouter** are trademarks of their respective companies.

All trademarks are used here solely for identification and interoperability purposes.

## License

This project is licensed under the [Apache License 2.0](LICENSE).

SkopaqTrader is a derivative work of [TradingAgents](https://github.com/TauricResearch/TradingAgents) by [TauricResearch](https://tauric.ai/), originally released under the Apache License 2.0. All original copyright and attribution notices are retained per the license terms.

---

<div align="center">
<sub><strong>Disclaimer:</strong> This software is for educational and research purposes only. It does not constitute financial, investment, or trading advice. Trading in financial markets carries substantial risk. The authors accept no liability for losses incurred through the use of this software. See the <a href="#important-legal-disclaimer">full disclaimer</a> at the top of this page.</sub>
</div>

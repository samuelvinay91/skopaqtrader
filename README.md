<div align="center">

<img src="assets/hero_banner.png" alt="SkopaqTrader AI Platform" style="max-width: 100%; height: auto; object-fit: contain;" />

# SkopaqTrader

**India's first self-evolving AI algorithmic trading platform, powered by INDstocks**

Built on [TradingAgents](https://github.com/TauricResearch/TradingAgents) (Apache 2.0) by TauricResearch

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab?logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-powered-00A67E)](https://langchain-ai.github.io/langgraph/)

</div>

---

## Overview

SkopaqTrader extends the [TradingAgents](https://github.com/TauricResearch/TradingAgents) multi-agent LLM framework with Indian equity market support, multi-model tiering, broker integration, and a self-evolving execution pipeline.

**Key capabilities:**

- **Self-Evolving Feedback Loop** — Post-trade reflection node analyzes past trades and injects history into the analyst context, enabling the system to learn from its wins and losses over time.
- **Persistent Agent Memory** — BM25-indexed memory store backed by Supabase for long-term strategic recall across all agent roles.
- **Multi-agent analysis** — Analyst team (market, news, social, fundamentals), bull/bear researchers, risk manager, and trader agent collaborate via LangGraph.
- **Multi-model tiering** — Per-role LLM assignment: Gemini 3 Flash (fast/cheap), Claude Opus 4.6 (deep reasoning), Grok (social/X), Perplexity Sonar (web-grounded news).
- **Semantic LLM Caching** — Built-in Redis LangCache provides a **45x speedup** on repeated queries and slashes API costs, with automatic semantic invalidation on memory updates.
- **Advanced Risk Management** — Features ATR-based position sizing, India VIX/NIFTY SMA market regime detection, NSE event calendar handling (F&O expiry, RBI policy), and sector concentration limits.
- **Live INDstocks Algo Trading** — Deep integration with **INDstocks** for seamless execution on Indian equities (NSE/BSE). Start in paper mode, graduate to live when ready.
- **Confidence-Scored Position Sizing** — The Risk Manager evaluates trades with strict confidence scores (50-100%). Position sizes are dynamically scaled based on this AI confidence level.
- **Parallel Scanner Engine** — 30-second multi-model screening cycle on the NIFTY 50 watchlist, wired directly to INDstocks batch quotes and 3 LLM screeners (Gemini, Grok, Perplexity) running concurrently.
- **Safety-First Execution** — Immutable position limits, persistent drawdown tracking, daily loss circuit breakers, and small-account exemptions.
- **Autonomous Trading Daemon** — Full session orchestrator: PRE_OPEN → SCANNING → ANALYZING → TRADING → MONITORING → CLOSING → REPORTING. Runs unattended on a cron schedule with graceful SIGTERM handling and tighter safety rules.
- **AI-Powered Position Monitor** — Three-tier exit logic (hard stop-loss, AI sell analyst, EOD safety net) with optional trailing stops and configurable poll intervals.
- **Min Profit Gate** — Two-layer protection against brokerage-eating-profit: prompt guidance to the sell analyst LLM + hard override in the monitor that blocks sells when net profit (after estimated brokerage) is below threshold.
- **Crypto Support** — On-chain (Blockchair), DeFi/tokenomics (DeFiLlama/CoinGecko), and funding rate (Binance Futures) analysts activate when `asset_class=crypto`.

<img src="assets/dashboard.png" alt="Skopaq Dashboard" style="max-width: 100%; height: auto;" />
*Professional, real-time command center for monitoring agent workflows, market scanners, and live INDstocks execution.*

- **Paper → Live pipeline** — Start paper, graduate to live when ready

> **Disclaimer:** This framework is for research and educational purposes. Trading performance varies based on models, data quality, and market conditions. [It is not financial, investment, or trading advice.](https://tauric.ai/disclaimer/)

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

    subgraph CoreSystem["SkopaqTrader Core - LangGraph"]
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
        INDstocks["INDstocks Broker<br/>NSE / BSE Trading"]:::external
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
    Router --> INDstocks
    Orchestrator -.-> Supabase
    Orchestrator -.-> Redis
    Router -. "Trade Result" .-> Orchestrator
    Orchestrator -. "Reflection" .-> DataAgents
```

*High-level overview of the SkopaqTrader architecture, connecting the user interfaces to the multi-agent AI team and the INDstocks execution engine.*

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
    participant Broker as INDstocks Broker

    User->>Orch: Request Analysis (e.g. RELIANCE)
    Orch->>Analysts: Gather Market, News, Social Data
    Note over Analysts: Gemini 3, Grok, Perplexity<br/>Accelerated by Redis LangCache
    Analysts-->>Orch: Formatted Data and Sentiment
    Orch->>Research: Generate Bull and Bear Thesis
    Note over Research: Deep reasoning via Claude Opus
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
    S5["5. Execute Trade<br/>Paper or Live via INDstocks"]:::highlight
    S6["6. Reflect and Learn<br/>System self-evolves from trade"]:::step

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
    INDapi["INDstocks API Batch Quote"]:::data
    CacheCheck{"Redis LangCache<br/>Semantic Check"}:::check
    CachedData["Return Cached Inference<br/>45x speedup"]:::llm

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

### CLI

```bash
# System health check
skopaq status

# Analyze a stock (no execution)
skopaq analyze RELIANCE
skopaq analyze TATAMOTORS --date 2026-02-28

# Analyze + execute (paper mode by default)
skopaq trade RELIANCE

# Run scanner cycle
skopaq scan --max-candidates 5

# Autonomous daemon (full session: scan → trade → monitor → close)
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
```

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
│   ├── broker/                 # INDstocks REST/WebSocket + Binance + paper engine
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
- **INDstocks tokens** are stored locally in `~/.skopaq/token.json` (gitignored) and validated on every daemon session start.
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

## License

This project is licensed under the [Apache License 2.0](LICENSE).

SkopaqTrader is a derivative work of [TradingAgents](https://github.com/TauricResearch/TradingAgents) by [TauricResearch](https://tauric.ai/), originally released under the Apache License 2.0. All original copyright and attribution notices are retained per the license terms.

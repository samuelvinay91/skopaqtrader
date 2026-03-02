<div align="center">

# SkopaqTrader

**India's first self-evolving AI trading platform**

Built on [TradingAgents](https://github.com/TauricResearch/TradingAgents) (Apache 2.0) by TauricResearch

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab?logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-powered-00A67E)](https://langchain-ai.github.io/langgraph/)

</div>

---

## Overview

SkopaqTrader extends the [TradingAgents](https://github.com/TauricResearch/TradingAgents) multi-agent LLM framework with Indian equity market support, multi-model tiering, broker integration, and a self-evolving execution pipeline.

**Key capabilities:**

- **Multi-agent analysis** — Analyst team (market, news, social, fundamentals), bull/bear researchers, risk manager, and trader agent collaborate via LangGraph
- **Multi-model tiering** — Per-role LLM assignment: Gemini 3 Flash (fast/cheap), Claude Opus 4.6 (deep reasoning), Grok (social/X), Perplexity Sonar (web-grounded news)
- **INDstocks broker integration** — REST + WebSocket for Indian equities (NSE/BSE), with paper trading engine
- **Scanner engine** — 30-second multi-model screening cycle on NIFTY 50 watchlist
- **Safety-first execution** — Immutable position limits, daily loss circuit breakers, stop-loss requirements
- **Paper → Live pipeline** — Start paper, graduate to live when ready

> **Disclaimer:** This framework is for research and educational purposes. Trading performance varies based on models, data quality, and market conditions. [It is not financial, investment, or trading advice.](https://tauric.ai/disclaimer/)

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   SkopaqTrader                       │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐ │
│  │ Scanner  │  │  CLI /   │  │   Next.js          │ │
│  │ Engine   │  │  FastAPI  │  │   Dashboard        │ │
│  └────┬─────┘  └────┬─────┘  └────────┬──────────┘ │
│       │              │                  │            │
│  ┌────▼──────────────▼──────────────────▼──────────┐│
│  │         SkopaqTradingGraph (Wrapper)             ││
│  │  ┌─────────────────────────────────────────┐    ││
│  │  │     TradingAgents (Upstream LangGraph)   │    ││
│  │  │  Analysts → Researchers → Trader → Risk  │    ││
│  │  └─────────────────────────────────────────┘    ││
│  └──────────────────┬──────────────────────────────┘│
│                     │                                │
│  ┌──────────────────▼──────────────────────────────┐│
│  │  Execution Pipeline                              ││
│  │  SafetyChecker → OrderRouter → Paper/Live Engine ││
│  └──────────────────┬──────────────────────────────┘│
│                     │                                │
│  ┌──────────────────▼──────────────────────────────┐│
│  │  INDstocks Broker  │  Supabase DB  │  Redis     ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

### Multi-Model Tiering

| Agent Role | Primary Model | Fallback |
|------------|---------------|----------|
| Market / Fundamentals Analyst | Gemini 3 Flash | — |
| Social Analyst | Grok 3 Mini (via OpenRouter) | Gemini 3 Flash |
| News Analyst | Perplexity Sonar Pro (via OpenRouter) | Gemini 3 Flash |
| Research Manager | Claude Opus 4.6 | Gemini 3 Flash |
| Risk Manager | Claude Opus 4.6 | Gemini 3 Flash |
| Bull / Bear / Debate Researchers | Gemini 3 Flash | — |
| Trader | Gemini 3 Flash | — |

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
│   ├── graph/                  # LangGraph orchestration
│   ├── dataflows/              # Data vendors (yfinance, INDstocks, etc.)
│   └── llm_clients/            # LLM factory (OpenAI, Google, Anthropic, etc.)
│
├── skopaq/                     # SkopaqTrader extensions
│   ├── broker/                 # INDstocks REST/WebSocket client
│   ├── cli/                    # Typer CLI commands
│   ├── config.py               # Pydantic Settings configuration
│   ├── constants.py            # Immutable safety rules
│   ├── db/                     # Supabase integration
│   ├── execution/              # Order pipeline + safety checker
│   ├── graph/                  # Upstream wrapper (SkopaqTradingGraph)
│   ├── llm/                    # Multi-model tiering + env bridge
│   └── scanner/                # Multi-model market scanner
│
├── frontend/                   # Next.js dashboard (Vercel)
├── supabase/                   # Database migrations
├── docker/                     # Dockerfile for Railway
├── tests/                      # Unit + integration tests
│   ├── unit/
│   └── integration/
│
├── UPSTREAM_CHANGES.md         # All modifications to vendored code
├── CONTRIBUTING.md             # Contribution guidelines
├── pyproject.toml              # Python project config
├── railway.toml                # Railway deployment config
└── LICENSE                     # Apache 2.0
```

## Testing

```bash
# Unit tests (no API keys needed)
python -m pytest tests/unit/ -v

# Integration tests (requires .env with real API keys)
python -m pytest tests/integration/ -v -m integration

# All tests with coverage
python -m pytest --cov=skopaq --cov=tradingagents -v
```

## Deployment

| Service | Purpose |
|---------|---------|
| **Railway** | Python backend (FastAPI + scheduler) |
| **Vercel** | Next.js frontend dashboard |
| **Supabase** | PostgreSQL database + Auth |
| **Upstash** | Serverless Redis |
| **Cloudflare Tunnel** | Static IP for INDstocks API |

See [`railway.toml`](railway.toml) and [`docker/Dockerfile`](docker/Dockerfile) for backend deployment config.

## Upstream Modifications

All changes to the vendored `tradingagents/` directory are documented in [`UPSTREAM_CHANGES.md`](UPSTREAM_CHANGES.md).

**Modification philosophy:** Minimal, surgical changes. The upstream graph runs as a black box via `propagate()`. Skopaq wraps it with execution, safety, and multi-model tiering.

Current upstream modifications:
1. `graph/setup.py` — Added `llm_map` support for per-role LLM assignment
2. `graph/trading_graph.py` — Pass `llm_map` from config to GraphSetup
3. `dataflows/indstocks.py` — New file: INDstocks data vendor
4. `dataflows/interface.py` — Register INDstocks in vendor list
5. `llm_clients/validators.py` — Added Claude 4.6 and Gemini 3 model IDs

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

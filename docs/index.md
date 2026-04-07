# SkopaqTrader

**AI Algorithmic Trading Platform for Indian Equities**

SkopaqTrader is an open-source AI trading platform that combines a 15-agent analysis pipeline with broker integration, options selling, and autonomous trading — all controllable from Claude Code, Telegram, or the CLI.

---

## What Makes It Different

| Feature | Description |
|---------|-------------|
| **Claude Code Native** | 23 MCP tools + 6 custom skills — trade directly from Claude Code |
| **15-Agent Pipeline** | 4 analysts, bull/bear debate, risk debate, trader — all perspectives before every trade |
| **Zero Extra LLM Cost** | Claude Code IS the analyst — no separate API calls needed |
| **Telegram Bot** | AI chatbot on your phone with scheduled scans and alerts |
| **Options Selling** | AI selects optimal OTM strikes with win probability and Greeks |
| **GTT Orders** | Set-and-forget trades — Zerodha watches 24/7 |
| **Auto-Notifications** | Every trade event fires Telegram alerts automatically |
| **Ollama Fallback** | Works offline with local models on Apple Silicon |
| **Docker Ready** | One image, 10 services — `docker compose up` |

## Quick Start

```bash
# 3 commands to start trading:
git clone https://github.com/samuelvinay91/skopaqtrader.git
cp .env.example .env        # Add your API keys
pip install -e .             # Install
skopaq chat                  # Start trading
```

Or with Docker:
```bash
docker pull samuelvinay91/skopaq
docker run -it --env-file .env samuelvinay91/skopaq chat
```

## Architecture at a Glance

```
User → Claude Code / Telegram / CLI
  ↓
MCP Server (23 tools)
  ↓
┌─────────────────────────────────┐
│ Analysis Pipeline               │
│  4 Analysts → Bull/Bear Debate  │
│  → Research Manager → Trader    │
│  → Risk Debate → Final Decision │
└─────────────────────────────────┘
  ↓
Safety Checker → Order Router
  ↓
Kite Connect / INDstocks / Paper Engine
  ↓
Telegram Notification
```

!!! warning "Disclaimer"
    This software is for **educational and research purposes only**. It is NOT financial advice. Trading involves substantial risk of loss. You are solely responsible for any trades executed.

## Next Steps

- [Installation](getting-started/installation.md) — Set up the platform
- [Quick Start](getting-started/quickstart.md) — Your first trade in 5 minutes
- [Claude Code Setup](claude-code/setup.md) — Integrate with Claude Code
- [Telegram Bot](telegram/setup.md) — Trade from your phone

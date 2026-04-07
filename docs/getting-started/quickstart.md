# Quick Start

Get from zero to your first AI-powered trade in 5 minutes.

## Option 1: Claude Code (Recommended)

The most powerful way — Claude Code becomes your trading terminal.

### Step 1: Register MCP Server

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "skopaq": {
      "command": "python3",
      "args": ["-m", "skopaq.mcp_server"]
    }
  }
}
```

### Step 2: Restart Claude Code

Open Claude Code in the `skopaqtrader` directory. You'll see 23 trading tools available.

### Step 3: Trade

```
/quote RELIANCE          # Get live quote
/analyze TCS             # Full 15-agent analysis
/scan                    # Find top trading candidates
/portfolio               # Check positions & P&L
/options NIFTY           # AI options selling recommendation
```

Or just talk naturally:

```
> "What's the best stock to buy today?"
> "Analyze HDFCBANK for me"
> "Set up a swing trade on RELIANCE with support at 1280"
```

## Option 2: Interactive Chat

```bash
skopaq chat
```

This launches a Claude Code-style REPL with:

- Streaming AI responses
- Slash commands (`/quote`, `/scan`, `/portfolio`)
- Tool execution panels
- Human-in-the-loop trade confirmation

## Option 3: CLI Commands

```bash
# Analyze (no execution)
skopaq analyze RELIANCE

# Analyze + execute (paper mode)
skopaq trade RELIANCE

# Market scan
skopaq scan --max-candidates 10

# Autonomous daemon
skopaq daemon --once --paper

# Position monitor
skopaq monitor
```

## Option 4: Telegram Bot

1. Search `@Skopaq_bot` on Telegram
2. Send `/start`
3. Chat naturally: "what's TCS at?" or "show my portfolio"

## Your First Paper Trade

=== "Claude Code"

    ```
    /trade RELIANCE
    ```
    
    Claude will:
    1. Fetch live data via MCP tools
    2. Run 15-agent analysis
    3. Present BUY/SELL/HOLD with confidence
    4. Ask for confirmation
    5. Execute paper trade

=== "CLI"

    ```bash
    skopaq trade RELIANCE
    ```

=== "Telegram"

    Send to @Skopaq_bot:
    ```
    trade RELIANCE
    ```

## Going Live

!!! danger "Real Money"
    Live trading uses real money. Start with paper mode until you're confident.

```bash
# Set in .env
SKOPAQ_TRADING_MODE=live

# For Kite Connect, login at:
# https://skopaq-trader.fly.dev/api/kite/login
```

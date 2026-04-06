---
name: scan
description: Scan market for trading opportunities using Claude's reasoning + live quotes. No external LLM API calls needed.
argument-hint: "[max_candidates]"
user-invocable: true
allowed-tools: mcp__skopaq__get_quote mcp__skopaq__get_historical WebSearch
---

# Scan Market — Claude-Native Scanner

You ARE the scanner. Use your own reasoning to identify the best trading candidates from live market data.

**IMPORTANT**: Use MCP tools (`mcp__skopaq__*`) for market data. Do NOT write Python/Bash code to call broker APIs directly.

## Your Task

Find the top trading opportunities (default: 5, or $ARGUMENTS if specified).

### Step 1: Get Market Pulse
- `WebSearch` for "NSE top gainers today" and "India stock market movers today"
- This gives you the universe of active stocks to evaluate

### Step 2: Fetch Live Data
For each promising symbol from Step 1, call MCP tool:
- `mcp__skopaq__get_quote` with symbol=SYMBOL — current price, change%, volume

Focus on symbols with:
- Change% > 1% (either direction — momentum)
- Unusual volume (significantly above average)
- Price near key levels

### Step 3: Quick Technical Check
For the top candidates, call:
- `mcp__skopaq__get_historical` — last 2 days of 15-min candles

Look for:
- Breakout patterns (price above recent range)
- Volume confirmation (rising volume on moves)
- Trend alignment (direction consistent across timeframes)

### Step 4: Rank and Present

Present results as a ranked table:

| Rank | Symbol | LTP (₹) | Change% | Volume | Signal | Score | Reason |
|------|--------|---------|---------|--------|--------|-------|--------|

Score each 0-100 based on:
- Technical setup strength (40%)
- Volume confirmation (30%)
- News/catalyst (30%)

Highlight any score > 80 as a strong pick.

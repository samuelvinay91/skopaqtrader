# Custom Slash Commands

SkopaqTrader ships 6 custom skills for Claude Code, defined in `.claude/skills/`. These are slash commands you type directly in the Claude Code prompt.

## Available Commands

| Command | Description | Skill File |
|---------|-------------|------------|
| `/quote SYMBOL` | Real-time stock quote | `.claude/skills/quote/SKILL.md` |
| `/analyze SYMBOL` | Full 15-agent analysis pipeline | `.claude/skills/analyze/SKILL.md` |
| `/scan [N]` | Market scan for top candidates | `.claude/skills/scan/SKILL.md` |
| `/portfolio` | Positions, holdings, funds, P&L | `.claude/skills/portfolio/SKILL.md` |
| `/trade SYMBOL` | Analysis + execution with confirmation | `.claude/skills/trade/SKILL.md` |
| `/options [SYMBOL] [STRATEGY]` | AI options selling recommendation | `.claude/skills/options/SKILL.md` |

## /quote SYMBOL

Get a live market quote with LTP, day range, bid/ask, and volume.

```
/quote RELIANCE
```

Claude fetches the quote via `mcp__skopaq__get_quote` and presents:

```
RELIANCE (NSE)
  LTP:    Rs 2,485.50 (+0.63%)
  Open:   Rs 2,470.00
  High:   Rs 2,498.00
  Low:    Rs 2,465.00
  Volume: 12,34,567
```

## /analyze SYMBOL

Runs the complete 15-agent analysis using Claude's own reasoning. This is the **Claude-native** pipeline -- Claude plays all 15 roles (4 analysts, bull/bear researchers, research manager, trader, 3 risk debaters, risk manager) using live data from MCP tools.

```
/analyze TCS
```

The output includes:

1. Four analyst reports (market, social, news, fundamentals)
2. Bull vs bear investment debate
3. Research manager verdict
4. Trader recommendation
5. Three-way risk debate (aggressive, conservative, neutral)
6. Final signal with confidence score

!!! note "Duration"
    Takes 1-3 minutes. Uses `gather_all_analysis_data` for data, then Claude reasons through each phase.

## /scan

Scan the market for trading opportunities. Claude searches for top movers, fetches live quotes, and ranks them by technical setup.

```
/scan        # Default: top 5 candidates
/scan 10     # Top 10 candidates
```

Output is a ranked table with symbol, LTP, change%, volume, signal, and score (0-100).

## /portfolio

Display the full portfolio state: cash balance, open positions with P&L, and delivery holdings.

```
/portfolio
```

Returns a formatted summary:

```
Funds:
  Available Cash:  Rs 9,87,654.00
  Used Margin:     Rs 1,12,346.00
  Collateral:      Rs 0.00

Positions (2):
  RELIANCE  10x @ Rs 2,400.00  LTP Rs 2,485.50  P&L +Rs 855.00
  TCS        5x @ Rs 3,800.00  LTP Rs 3,750.00  P&L -Rs 250.00
```

## /trade SYMBOL

End-to-end trade workflow: Claude analyzes the stock, calculates position size, validates safety, and executes after you confirm.

```
/trade INFY
```

**Workflow:**

1. Fetches live quote + historical data
2. Runs technical + news analysis
3. Generates BUY/SELL/HOLD signal
4. Calculates quantity (1% capital risk per trade)
5. Calls `check_safety` to validate
6. Presents the trade plan and asks for confirmation
7. Executes via `place_order` only after you say yes

!!! warning "Paper mode is default"
    All trades execute in paper mode unless you have explicitly configured live trading. Claude will never auto-execute without your confirmation.

## /options

AI-powered options selling analysis. Fetches the option chain, selects the optimal OTM strike, and presents a recommendation with full risk metrics.

```
/options                         # Default: NIFTY SHORT_PUT
/options BANKNIFTY SHORT_CALL    # Specific underlying + strategy
/options RELIANCE SHORT_STRANGLE # Stock options
```

**Strategies:**

| Strategy | Market View | What It Does |
|----------|-------------|--------------|
| `SHORT_PUT` | Bullish | Sell OTM put below support |
| `SHORT_CALL` | Bearish | Sell OTM call above resistance |
| `SHORT_STRANGLE` | Neutral | Sell both OTM put + call |

The output includes strike selection, premium, max profit/loss, margin, stop-loss, and win probability estimate.

!!! tip "Requires Kite Connect"
    Options data comes from Zerodha's option chain API. Login via the Telegram bot (`/login`) or visit `https://skopaq-trader.fly.dev/api/kite/login`.

## How Skills Work

Each skill is a `SKILL.md` file in `.claude/skills/<name>/`. It contains:

- **YAML frontmatter**: name, description, allowed MCP tools
- **Markdown body**: Detailed instructions for Claude on how to execute the skill

Claude Code reads the skill file and follows its instructions, calling the listed MCP tools as needed. See [Adding Skills](../contributing/skills.md) for how to create new ones.

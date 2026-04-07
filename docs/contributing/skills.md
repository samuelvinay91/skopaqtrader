# Adding Claude Code Skills

Skills are custom slash commands for Claude Code, defined as `SKILL.md` files. Each skill instructs Claude on how to perform a specific task using MCP tools.

## Skill File Format

Skills live in `.claude/skills/<name>/SKILL.md`. Each file has YAML frontmatter and a Markdown body.

### Frontmatter

```yaml
---
name: my-skill
description: What this skill does (shown in Claude Code UI)
argument-hint: "<SYMBOL>"
user-invocable: true
allowed-tools: mcp__skopaq__get_quote mcp__skopaq__get_historical WebSearch
---
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Skill identifier (used as `/name` command) |
| `description` | Yes | Short description shown in Claude Code |
| `argument-hint` | No | Placeholder shown after the slash command |
| `user-invocable` | Yes | Set to `true` for user-facing skills |
| `allowed-tools` | No | Space-separated list of MCP tools the skill can use |

### Body

The Markdown body contains detailed instructions for Claude. Use `$ARGUMENTS` to reference what the user typed after the slash command.

```markdown
# My Skill

You will perform X using data from MCP tools.

**Symbol to process: $ARGUMENTS**

## Step 1: Fetch Data
Call `mcp__skopaq__get_quote` with symbol=$ARGUMENTS.

## Step 2: Analyze
Based on the data, provide your analysis.

## Step 3: Present Results
Format as a table with these columns: ...
```

## Example: Creating a /watchlist Skill

### Step 1: Create the Directory

```bash
mkdir -p .claude/skills/watchlist
```

### Step 2: Write the SKILL.md

```markdown
---
name: watchlist
description: Monitor a list of stocks with live quotes and alerts.
argument-hint: "RELIANCE,TCS,INFY"
user-invocable: true
allowed-tools: mcp__skopaq__get_quote mcp__skopaq__get_historical
---

# Watchlist Monitor

Monitor the given stocks and highlight any with unusual activity.

**Stocks: $ARGUMENTS**

## Step 1: Fetch Quotes
For each symbol in the comma-separated list, call:
- `mcp__skopaq__get_quote` with symbol=SYMBOL

## Step 2: Analyze
For each stock, check:
- Change% > 2% (significant move)
- Volume unusually high
- Price near day high or day low

## Step 3: Present
Show a table:
| Symbol | LTP | Change% | Volume | Alert |

Highlight any stocks with unusual activity.
```

### Step 3: Test

In Claude Code, type:

```
/watchlist RELIANCE,TCS,INFY,HDFCBANK
```

## Existing Skills Reference

| Skill | File | Tools Used |
|-------|------|-----------|
| `/quote` | `.claude/skills/quote/SKILL.md` | `get_quote` |
| `/analyze` | `.claude/skills/analyze/SKILL.md` | `gather_all_analysis_data`, `get_quote`, `recall_agent_memories`, `check_safety` |
| `/scan` | `.claude/skills/scan/SKILL.md` | `get_quote`, `get_historical`, `WebSearch` |
| `/portfolio` | `.claude/skills/portfolio/SKILL.md` | `get_positions`, `get_holdings`, `get_funds` |
| `/trade` | `.claude/skills/trade/SKILL.md` | `get_quote`, `get_historical`, `get_funds`, `check_safety`, `place_order` |
| `/options` | `.claude/skills/options/SKILL.md` | `get_option_chain`, `suggest_option_trade`, `get_quote` |

## Best Practices

### Use MCP Tools, Not Code

Skills should instruct Claude to use MCP tools, not write Python code:

```markdown
# Good
Call `mcp__skopaq__get_quote` with symbol=$ARGUMENTS.

# Bad
Run this Python code:
```python
from skopaq.broker.client import INDstocksClient
...
```

### Restrict Allowed Tools

Only list the tools the skill actually needs in `allowed-tools`. This prevents the skill from accidentally using destructive tools:

```yaml
# Specific — only read-only tools
allowed-tools: mcp__skopaq__get_quote mcp__skopaq__get_historical

# Not recommended — allows everything
# (no allowed-tools field = all tools available)
```

### Ask for Confirmation Before Actions

Any skill that modifies state (places orders, saves data) should ask for user confirmation:

```markdown
## Step 4: Confirm
Present the trade plan and ask:
"Shall I execute this trade? (y/n)"

**NEVER execute without explicit user confirmation.**
```

### Use $ARGUMENTS

The `$ARGUMENTS` variable contains everything the user typed after the slash command:

```
/analyze TCS         → $ARGUMENTS = "TCS"
/scan 10             → $ARGUMENTS = "10"
/options NIFTY PUT   → $ARGUMENTS = "NIFTY PUT"
```

Handle the case where `$ARGUMENTS` is empty by providing sensible defaults.

### Structure with Clear Steps

Break the skill into numbered steps. Claude follows structured instructions better than freeform text:

```markdown
## Step 1: Gather Data
...
## Step 2: Analyze
...
## Step 3: Present Results
...
```

## Debugging Skills

If a skill is not working:

1. Check the file is at `.claude/skills/<name>/SKILL.md` (exact path matters)
2. Verify the YAML frontmatter is valid (no tabs, proper indentation)
3. Ensure `user-invocable: true` is set
4. Check that listed MCP tools exist and are spelled correctly
5. Restart Claude Code after adding or modifying skills

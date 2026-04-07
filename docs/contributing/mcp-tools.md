# Adding MCP Tools

MCP tools are defined in `skopaq/mcp_server.py` using the `@mcp.tool()` decorator from FastMCP. Each tool is an async function that returns a JSON string.

## Anatomy of a Tool

```python
@mcp.tool()
async def my_tool(symbol: str, days: int = 5) -> str:
    """Short description shown to the AI.

    Longer description with details about what the tool does,
    when to use it, and what it returns.

    Args:
        symbol: Stock symbol (e.g. RELIANCE, TCS).
        days: Number of days of history (default 5).
    """
    config = _get_config()

    # ... implementation ...

    return json.dumps({
        "symbol": symbol,
        "result": "...",
    })
```

### Key rules:

1. **Async function** -- All tools must be `async def`
2. **Returns `str`** -- Always return `json.dumps(...)`, never raw dicts
3. **Docstring is the description** -- The AI reads this to decide when to use the tool
4. **Type hints on all args** -- FastMCP generates the tool schema from type hints
5. **Default values** -- Provide sensible defaults for optional parameters

## Step-by-Step: Adding a New Tool

### Step 1: Define the Function

Add your tool in the appropriate section of `skopaq/mcp_server.py`:

```python
# ── My New Section ──────────────────────────────────────────────────────────

@mcp.tool()
async def get_option_greeks(
    symbol: str = "NIFTY",
    strike: float = 0,
    option_type: str = "CE",
) -> str:
    """Calculate option Greeks (delta, gamma, theta, vega) for a specific contract.

    Args:
        symbol: Underlying symbol (NIFTY, BANKNIFTY, or stock).
        strike: Strike price.
        option_type: CE (call) or PE (put).
    """
    kite = _get_kite()
    if not kite:
        return json.dumps({"error": "Kite not connected"})

    try:
        # Your implementation here
        greeks = calculate_greeks(symbol, strike, option_type)

        return json.dumps({
            "symbol": symbol,
            "strike": strike,
            "type": option_type,
            "delta": greeks.delta,
            "gamma": greeks.gamma,
            "theta": greeks.theta,
            "vega": greeks.vega,
        })

    except Exception as exc:
        logger.exception("Greeks calculation failed")
        return json.dumps({"error": str(exc)})
```

### Step 2: Handle Errors Gracefully

Always catch exceptions and return structured error JSON:

```python
try:
    result = await some_operation()
    return json.dumps({"success": True, "data": result})
except Exception as exc:
    logger.exception("Operation failed")
    return json.dumps({"error": str(exc)})
```

This ensures the AI always gets a parseable response.

### Step 3: Use Lazy Infrastructure

Access shared infrastructure via the lazy helpers:

```python
config = _get_config()    # SkopaqConfig (cached)
router = _get_router()    # OrderRouter + PaperEngine (cached)
kite = _get_kite()        # KiteClient or None
```

Do not import and instantiate these at module level -- it would slow down server startup.

### Step 4: Write Tests

Add a test in `tests/unit/` that mocks external dependencies:

```python
# tests/unit/test_mcp_greeks.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
@patch("skopaq.mcp_server._get_kite")
async def test_get_option_greeks(mock_kite):
    from skopaq.mcp_server import get_option_greeks

    mock_kite.return_value = AsyncMock()
    # ... mock the calculation
    result = await get_option_greeks("NIFTY", 24000, "CE")
    data = json.loads(result)
    assert "delta" in data
```

### Step 5: Update Tests and Permissions

After adding your tool:

1. Update `tests/unit/chat/test_mcp_server.py` -- add tool name to the expected set
2. Add to `.claude/settings.json` permissions if it should be auto-allowed
3. Run tests: `python3 -m pytest tests/unit/ -x -q`

### Step 6: Add to Skills (Optional)

If your tool should be available via a slash command, add it to an existing skill's `allowed-tools` or create a new skill:

```yaml
# .claude/skills/greeks/SKILL.md
---
name: greeks
description: Calculate option Greeks for a contract
allowed-tools: mcp__skopaq__get_option_greeks mcp__skopaq__get_option_chain
---
```

## Design Guidelines

### Docstring Quality

The docstring is critical -- it is the only thing the AI sees when deciding which tool to use:

```python
# Good: specific, mentions when to use it
"""Calculate implied volatility for an option contract.

Use this to compare IV across strikes and identify overpriced/underpriced options.
Returns IV as a percentage along with the historical IV rank.

Args:
    symbol: Underlying symbol.
"""

# Bad: vague, no context
"""Get some option data."""
```

### Return Structure

Always return a flat JSON object with clear field names:

```python
# Good
return json.dumps({
    "symbol": "NIFTY",
    "iv": 15.3,
    "iv_rank": 45,
    "iv_percentile": 62,
})

# Bad: nested, unclear
return json.dumps({
    "data": {"s": "NIFTY", "vals": [15.3, 45, 62]}
})
```

### Kite-Dependent Tools

If your tool requires Kite Connect, check for it and return a clear error:

```python
kite = _get_kite()
if not kite:
    return json.dumps({"error": "Kite not connected. Login first."})
```

### Size Limits

Truncate large responses to avoid overwhelming the AI's context window:

```python
# Limit text fields
return json.dumps({
    "news": news_text[:3000],  # Cap at 3000 chars
    "candles": candles[-20:],   # Last 20 only
})
```

## Tool Naming Conventions

| Pattern | Example | When |
|---------|---------|------|
| `get_*` | `get_quote`, `get_funds` | Read-only data retrieval |
| `place_*` | `place_order`, `place_gtt_order` | Actions that create something |
| `list_*` | `list_gtt_orders` | List collections |
| `gather_*` | `gather_market_data` | Fetch raw data for analysis |
| `check_*` | `check_safety` | Validation tools |
| `setup_*` | `setup_swing_trade` | Multi-step workflows |
| `suggest_*` | `suggest_option_trade` | AI recommendations |

## File Reference

| File | Purpose |
|------|---------|
| `skopaq/mcp_server.py` | All tool definitions (add your tool here) |
| `skopaq/config.py` | Configuration (if your tool needs new config) |
| `.claude/.mcp.json` | MCP server registration for Claude Code |
| `.claude/skills/*/SKILL.md` | Skill files that reference tools |

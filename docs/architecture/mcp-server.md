# MCP Server Architecture

The MCP (Model Context Protocol) server is how SkopaqTrader integrates with Claude Code and other AI assistants. It exposes 23 tools via the FastMCP framework over stdio transport.

## What Is MCP?

MCP is a protocol that allows AI assistants to call external tools. Instead of the AI writing Python code to access your broker, it calls structured MCP tools that handle authentication, error handling, and data formatting.

```
AI Assistant (Claude Code)
       │
       │  MCP Protocol (stdio)
       ▼
  skopaq/mcp_server.py
       │
       ├── Broker APIs (Kite Connect, INDstocks)
       ├── LLM Providers (Gemini, Claude, Grok)
       ├── Analysis Pipeline (LangGraph agents)
       └── Memory Store (Supabase)
```

## FastMCP Framework

The server uses [FastMCP](https://github.com/jlowin/fastmcp), a Python framework for building MCP servers. Tools are defined as decorated async functions:

```python
from mcp.server import FastMCP

mcp = FastMCP(
    name="SkopaqTrader",
    instructions="SkopaqTrader MCP server for Indian equity trading...",
)

@mcp.tool()
async def get_quote(symbol: str) -> str:
    """Get a real-time market quote for a stock symbol."""
    # ... implementation
    return json.dumps({"symbol": symbol, "ltp": 2485.50, ...})
```

Key design principles:

- **All tools are async** -- They can call async broker APIs without blocking
- **All tools return JSON strings** -- Structured data that Claude can parse
- **Lazy initialization** -- Infrastructure (config, broker clients) is built on first tool call, not at import time

## Transport

The server uses **stdio transport** -- it reads requests from stdin and writes responses to stdout. This is the default transport for Claude Code MCP servers.

```json
// .claude/.mcp.json
{
  "mcpServers": {
    "skopaq": {
      "command": "python3",
      "args": ["-m", "skopaq.mcp_server"]
    }
  }
}
```

Claude Code launches the Python process and communicates with it over pipes. No network ports are needed.

## Lazy Infrastructure

To keep startup fast, the server uses lazy initialization:

```python
_infra_cache: dict = {}

def _get_config():
    if "config" not in _infra_cache:
        from skopaq.config import SkopaqConfig
        from skopaq.llm import bridge_env_vars
        config = SkopaqConfig()
        bridge_env_vars(config)
        _infra_cache["config"] = config
    return _infra_cache["config"]
```

The first tool call triggers initialization of:

1. `SkopaqConfig` -- Loads `.env` and validates all settings
2. `bridge_env_vars()` -- Copies `SKOPAQ_*` to standard env vars for upstream compatibility
3. `OrderRouter` + `PaperEngine` -- Paper trading infrastructure
4. `KiteClient` -- Kite Connect client (if credentials available)

Subsequent calls reuse cached objects.

## Broker Fallback

Market data tools try Kite Connect first, then fall back to INDstocks:

```python
@mcp.tool()
async def get_quote(symbol: str) -> str:
    kite = _get_kite()
    if kite:
        q = await kite.get_quote(f"NSE:{symbol}", symbol=symbol)
    else:
        # Fall back to INDstocks
        async with INDstocksClient(config, token_mgr) as client:
            q = await client.get_quote(scrip_code, symbol=symbol)
    return json.dumps({...})
```

This means the tools work whether or not Kite is connected.

## Tool Categories

The 23 tools are organized into categories:

| Category | Tools | Source |
|----------|-------|--------|
| Market Data | `get_quote`, `get_historical` | Kite / INDstocks |
| Portfolio | `get_positions`, `get_holdings`, `get_funds`, `get_orders` | Kite / Paper |
| Analysis | `analyze_stock`, `scan_market`, `check_safety` | LLM pipeline |
| Data Gathering | `gather_*` (5 tools), `recall_agent_memories`, `save_trade_reflection` | Dataflows / Supabase |
| Execution | `place_order`, `system_status` | Order router |
| Options | `get_option_chain`, `suggest_option_trade` | Kite Connect |
| GTT | `place_gtt_order`, `list_gtt_orders`, `setup_swing_trade` | Kite Connect |

## Error Handling

All tools catch exceptions and return structured error JSON:

```python
try:
    chain = await fetch_option_chain(kite, symbol, expiry_index)
    return json.dumps({...})
except Exception as exc:
    logger.exception("Option chain fetch failed")
    return json.dumps({"error": str(exc)})
```

This ensures Claude always gets a parseable response, even on failure.

## Running Standalone

For debugging, run the server directly:

```bash
python -m skopaq.mcp_server
```

It will start and wait for MCP messages on stdin. You can also run it inside Docker:

```bash
docker run -it --env-file .env samuelvinay91/skopaq:latest mcp
```

## File Reference

| File | Purpose |
|------|---------|
| `skopaq/mcp_server.py` | MCP server with all 23 tool definitions |
| `.claude/.mcp.json` | Claude Code MCP server configuration |
| `skopaq/config.py` | Configuration loaded by `_get_config()` |
| `skopaq/llm/env_bridge.py` | Environment variable bridging |
| `skopaq/broker/kite_client.py` | Kite Connect broker client |
| `skopaq/options/chain.py` | Option chain fetcher |
| `skopaq/options/gtt.py` | GTT order management |

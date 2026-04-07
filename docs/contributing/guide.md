# Contributing Guide

SkopaqTrader is built on vendored TradingAgents (Apache 2.0) with a custom `skopaq/` layer. Contributions to the `skopaq/` layer are welcome.

## Getting Started

### Step 1: Fork and Clone

```bash
git clone https://github.com/your-username/skopaqtrader.git
cd skopaqtrader
```

### Step 2: Set Up Environment

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
# Edit .env with your API keys (optional for unit tests)
```

### Step 3: Run Tests

```bash
# Unit tests (no API keys needed, ~540 tests)
python3 -m pytest tests/unit/ -x -q

# Specific test file
python3 -m pytest tests/unit/execution/test_daemon.py -v

# Integration tests (requires .env with real keys)
python3 -m pytest tests/integration/ -v -m integration
```

## Development Workflow

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
```

Branch naming conventions:

| Prefix | Use |
|--------|-----|
| `feature/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Code restructuring |
| `docs/` | Documentation changes |
| `test/` | Test additions/fixes |

### 2. Make Changes

Follow these guidelines:

- **Edit `skopaq/` only** -- Avoid modifying `tradingagents/` unless absolutely necessary
- **Write tests** -- Every new feature needs unit tests in `tests/unit/`
- **Type hints** -- Use type annotations on all function signatures
- **Docstrings** -- Document all public functions and classes
- **Pydantic v2** -- Use attribute access (`model.field`), not dict access

### 3. Run Tests

```bash
# Run all unit tests
python3 -m pytest tests/unit/ -x -q

# Run with coverage
python3 -m pytest tests/unit/ --cov=skopaq --cov-report=term-missing
```

All unit tests must pass before submitting a PR.

### 4. Submit a Pull Request

```bash
git add -A
git commit -m "feat: description of your change"
git push origin feature/your-feature-name
```

Then open a PR on GitHub targeting the `main` branch.

## Code Organization

Know where to put your code:

| Directory | What Goes Here |
|-----------|---------------|
| `skopaq/agents/` | AI agent logic (sell analyst, etc.) |
| `skopaq/api/` | FastAPI endpoints |
| `skopaq/broker/` | Broker integrations (Kite, INDstocks) |
| `skopaq/cli/` | CLI commands and display |
| `skopaq/db/` | Database clients and repositories |
| `skopaq/execution/` | Order execution, safety, monitoring |
| `skopaq/graph/` | LangGraph pipeline wrapper |
| `skopaq/llm/` | LLM tiering, caching, env bridging |
| `skopaq/memory/` | Agent memory and reflection |
| `skopaq/options/` | Options chain, strategies, GTT |
| `skopaq/risk/` | Risk management (ATR sizing, regime) |
| `skopaq/scanner/` | Market scanner engine |

## Testing Patterns

### Unit Tests

- Mock all external dependencies (broker APIs, LLM providers)
- No API keys needed
- Fast execution (< 30 seconds for full suite)

```python
from unittest.mock import AsyncMock, patch

@patch("skopaq.broker.client.INDstocksClient")
async def test_get_quote(mock_client):
    mock_client.return_value.get_quote.return_value = Quote(
        symbol="TCS", ltp=3800.0, ...
    )
    # ... test logic
```

### Async Tests

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result.success
```

### Patch Targets

!!! warning "Common gotcha"
    When a function is imported inside a method body (common in `daemon.py`), patch at the **source module**, not the importing module:

    ```python
    # Correct
    @patch("skopaq.cli.main._run_scan")

    # Wrong — this patches a different reference
    @patch("skopaq.execution.daemon._run_scan")
    ```

## Upstream Changes

If you must modify `tradingagents/`:

1. Keep changes minimal and surgical
2. Document in `UPSTREAM_CHANGES.md`
3. Ensure backward compatibility
4. Add a comment in the modified file explaining why

## Key Conventions

1. **Safety rules are immutable** -- Never modify `SafetyRules` at runtime
2. **Paper mode is default** -- All new features must default to paper trading
3. **No secrets in code** -- All credentials via environment variables
4. **Rich output** -- CLI display uses Rich tables/panels via `skopaq/cli/display.py`
5. **Pydantic v2** -- Use Pydantic v2 models with attribute access

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add new MCP tool for option Greeks
fix: correct timestamp conversion in historical data
refactor: simplify safety checker validation logic
docs: add GTT orders documentation
test: add unit tests for Kite client
```

## Questions?

Open an issue on GitHub or reach out via the repository discussions.

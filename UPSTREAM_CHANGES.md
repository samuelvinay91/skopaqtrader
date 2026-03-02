# Upstream Changes Log

Documents all modifications made to files under `tradingagents/` (vendored from TauricResearch/TradingAgents v0.2.0).

**Upstream tag:** `upstream-v0.2.0`
**Diff command:** `git diff upstream-v0.2.0..HEAD -- tradingagents/`

## Changes

### Phase 2: Intelligence Layer

#### 1. `tradingagents/graph/setup.py` — Multi-model tiering

**What:** Added per-role LLM assignment via an optional `llm_map` dict.

- `GraphSetup.__init__` now accepts `llm_map: Optional[Dict[str, Any]]`
- New `_get_llm(role, deep=False)` method looks up role in map, falls back to `_default`, then to the original `quick_thinking_llm`/`deep_thinking_llm`
- All `create_*_analyst`, `create_*_researcher`, `create_*_manager` calls use `self._get_llm("role_name")` instead of hard-coded LLM references

**Why:** Enables multi-model tiering (Gemini Flash for market/fundamentals, Grok for social, Perplexity for news, Claude Sonnet for risk/research) without changing agent code.

**Backward compatible:** Yes — when `llm_map` is `None` (default), behavior is identical to upstream.

---

#### 2. `tradingagents/graph/trading_graph.py` — Pass llm_map to GraphSetup

**What:** Reads `llm_map` from `self.config` and passes it to `GraphSetup` constructor.

**Lines changed:** ~3 lines in `setup_graph()`.

**Backward compatible:** Yes — if config has no `llm_map` key, `None` is passed and upstream behavior is preserved.

---

#### 3. `tradingagents/dataflows/indstocks.py` — NEW FILE (INDstocks data vendor)

**What:** Added `get_stock_data_indstocks()` as a drop-in vendor for fetching OHLCV data from the INDstocks API. Includes:

- `_run_async()` sync-to-async bridge (handles both no-loop and existing-loop scenarios)
- `_fetch_historical()` / `_fetch_quote()` async helpers
- CSV output format matching yfinance for zero-change agent compatibility

**Not a modification** — purely additive new file.

---

#### 4. `tradingagents/dataflows/interface.py` — Register INDstocks vendor

**What:**
- Added `from .indstocks import get_stock_data_indstocks`
- Added `"indstocks"` as first entry in `VENDOR_LIST`
- Registered `get_stock_data_indstocks` in `VENDOR_METHODS["get_stock_data"]`

**Why:** INDstocks is the primary data source for Indian equities. Position as first vendor gives it priority in the fallback chain.

**Backward compatible:** Yes — other vendors still present as fallbacks. If INDstocks token is missing, `route_to_vendor()` falls through to yfinance/alpha_vantage.

---

### Phase 2.5: Paper Trading Enablement

#### 5. `tradingagents/agents/utils/technical_indicators_tools.py` — Handle comma-separated indicators

**What:** Modified `get_indicators()` to split comma-separated indicator strings and fetch each separately.

**Why:** LLMs (Gemini 3 Flash) sometimes batch multiple indicators into a single tool call: `"close_50_sma,close_200_sma,rsi,macd"`. The original code passed this as-is, causing `ValueError: Indicator ... is not supported`.

**Lines changed:** Added ~10 lines of splitting/combining logic after the docstring.

**Backward compatible:** Yes — single indicators work unchanged. Comma-separated strings are transparently split and results combined.

---

#### 6. `tradingagents/dataflows/interface.py` — yfinance symbol suffix for non-US markets

**What:**
- Added `_SYMBOL_ARG_METHODS` frozenset listing methods where first arg is a symbol
- Added `_apply_yfinance_suffix()` helper that appends a configurable suffix (e.g., `.NS`)
- Modified `route_to_vendor()` to call `_apply_yfinance_suffix()` when routing to yfinance

**Why:** yfinance requires exchange suffixes for non-US markets (e.g., `RELIANCE.NS` for NSE India). Upstream passes bare symbols. Rather than modifying every yfinance function, the suffix is applied at the routing layer.

**Backward compatible:** Yes — suffix defaults to empty string (`""`) in `DEFAULT_CONFIG`, so no change for US markets.

---

#### 7. `tradingagents/default_config.py` — Added yfinance_symbol_suffix config key

**What:** Added `"yfinance_symbol_suffix": ""` to `DEFAULT_CONFIG`.

**Why:** Configurable per deployment — set to `.NS` for India, `.L` for London, etc.

**Backward compatible:** Yes — defaults to empty string (no suffix).

---

### Performance: Parallel Analyst Execution

#### 9. `tradingagents/agents/utils/agent_states.py` — State reducers for parallel fan-out

**What:** Replaced string-annotation `Annotated[Type, "description"]` with reducer-annotation `Annotated[Type, reducer_fn]` on all `AgentState` fields (except `messages` which already has `add_messages`).

Added three reducer functions:
- `_last_str(a, b)` — keeps latest non-empty string
- `_last_invest_state(a, b)` — keeps `InvestDebateState` with higher count
- `_last_risk_state(a, b)` — keeps `RiskDebateState` with higher count

**Why:** LangGraph's default `LastValue` channel throws `InvalidUpdateError` when multiple parallel branches converge (fan-in). Custom reducers enable safe state merging during parallel analyst execution.

**Backward compatible:** Yes — reducers are semantically identical to `LastValue` for sequential execution. Only takes effect when parallel branches merge.

---

#### 10. `tradingagents/graph/setup.py` — Parallel analyst fan-out/fan-in

**What:**
- Changed graph wiring from sequential analyst chain to parallel fan-out: `START → [all analysts simultaneously]`
- Replaced per-analyst `Msg Clear` nodes with no-op `_analyst_done` pass-throughs
- Added single `"Clear Analyst Messages"` node after the fan-in point
- Fan-in: all `Done *` nodes → `Clear Analyst Messages` → `Bull Researcher`

**Why:** All 4 analysts are completely independent (separate tools, separate state fields). Running them in parallel saves time proportional to the non-longest analyst phase. Measured ~18% improvement (4m 46s → 3m 55s).

**Backward compatible:** Yes — same graph semantics, same outputs. Analysts just run concurrently.

---

#### 11. `tradingagents/graph/conditional_logic.py` — Done node routing

**What:** Changed `should_continue_*` return values from `"Msg Clear X"` to `"Done X"` to match the new no-op Done nodes.

**Why:** Per-analyst `Msg Clear` nodes were replaced with `Done *` pass-throughs to avoid `RemoveMessage` conflicts during parallel execution (multiple branches trying to delete the same initial message ID).

**Backward compatible:** Yes — no semantic change. Just different node names in the graph.

---

### Bugfix: Symbol suffix stripping

#### 8. `tradingagents/dataflows/indstocks.py` — Strip `.NS`/`.BO` suffixes

**What:** Added `_normalize_symbol()` helper and call it at the top of `_resolve_scrip_code()`.

**Why:** LLM agents (trained on Yahoo Finance conventions) often generate `RELIANCE.NS` instead of bare `RELIANCE`. The yfinance suffix logic in `interface.py` only *adds* `.NS` for the yfinance vendor — it doesn't *remove* it for INDstocks. This caused `ValueError: Symbol 'RELIANCE.NS' not found in NSE instruments`.

**Backward compatible:** Yes — bare symbols pass through unchanged.

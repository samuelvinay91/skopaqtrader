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

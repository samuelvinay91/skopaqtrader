"""Tests for the Redis LangCache semantic cache module."""

import json
import pytest
from dataclasses import dataclass
from unittest.mock import MagicMock, patch, PropertyMock

from langchain_core.outputs import Generation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_generations(text: str = "Hello world") -> list[Generation]:
    """Create a simple list of Generation objects for testing."""
    return [Generation(text=text, generation_info={"model": "test"})]


def _make_config(
    enabled: bool = True,
    api_key: str = "test-key",
    server_url: str = "https://test.langcache.redis.io",
    cache_id: str = "test-cache-id",
    threshold: float = 0.90,
):
    """Create a mock SkopaqConfig with langcache fields."""
    from pydantic import SecretStr

    config = MagicMock()
    config.langcache_enabled = enabled
    config.langcache_api_key = SecretStr(api_key)
    config.langcache_server_url = server_url
    config.langcache_cache_id = cache_id
    config.langcache_threshold = threshold
    return config


# ---------------------------------------------------------------------------
# Serialisation tests
# ---------------------------------------------------------------------------

class TestSerialization:
    """Tests for Generation serialisation/deserialisation round-trip."""

    def test_roundtrip_simple(self):
        from skopaq.llm.cache import _serialize_generations, _deserialize_generations

        original = _make_generations("Test response")
        serialized = _serialize_generations(original)
        restored = _deserialize_generations(serialized)

        assert len(restored) == 1
        assert restored[0].text == "Test response"
        assert restored[0].generation_info == {"model": "test"}

    def test_roundtrip_multiple(self):
        from skopaq.llm.cache import _serialize_generations, _deserialize_generations

        original = [
            Generation(text="First", generation_info={"idx": 0}),
            Generation(text="Second", generation_info=None),
        ]
        restored = _deserialize_generations(_serialize_generations(original))

        assert len(restored) == 2
        assert restored[0].text == "First"
        assert restored[1].text == "Second"
        assert restored[1].generation_info is None

    def test_serialized_is_valid_json(self):
        from skopaq.llm.cache import _serialize_generations

        gens = _make_generations("JSON test")
        data = _serialize_generations(gens)
        parsed = json.loads(data)  # Must not raise

        assert isinstance(parsed, list)
        assert parsed[0]["text"] == "JSON test"


class TestModelHash:
    """Tests for LLM string hashing (model partitioning)."""

    def test_deterministic(self):
        from skopaq.llm.cache import _model_hash

        h1 = _model_hash("google:gemini-3-flash")
        h2 = _model_hash("google:gemini-3-flash")
        assert h1 == h2

    def test_different_models_different_hashes(self):
        from skopaq.llm.cache import _model_hash

        h1 = _model_hash("google:gemini-3-flash")
        h2 = _model_hash("anthropic:claude-opus-4-6")
        assert h1 != h2

    def test_hash_length(self):
        from skopaq.llm.cache import _model_hash

        h = _model_hash("any-llm-string")
        assert len(h) == 16  # Truncated SHA-256

    def test_namespace_prompt_raw_includes_hash_and_prompt(self):
        """Non-JSON prompt uses raw fallback with model hash + content hash."""
        from skopaq.llm.cache import _namespace_prompt, _model_hash
        import hashlib

        text = "Analyze RELIANCE"
        ns = _namespace_prompt(text, "google:gemini-3-flash")
        model_hash = _model_hash("google:gemini-3-flash")
        content_hash = hashlib.sha256(text.encode()).hexdigest()[:8]
        expected = f"[m:{model_hash}][c:{content_hash}] {text}"
        assert ns == expected

    def test_namespace_prompt_langchain_json_extracts_human(self):
        """LangChain-serialized JSON extracts the human message content."""
        from skopaq.llm.cache import _namespace_prompt, _model_hash
        import json

        messages = [
            {"lc": 1, "type": "constructor",
             "id": ["langchain", "schema", "messages", "SystemMessage"],
             "kwargs": {"content": "You are a financial analyst.", "type": "system"}},
            {"lc": 1, "type": "constructor",
             "id": ["langchain", "schema", "messages", "HumanMessage"],
             "kwargs": {"content": "Analyze RELIANCE stock fundamentals", "type": "human"}},
        ]
        prompt = json.dumps(messages)
        ns = _namespace_prompt(prompt, "google:gemini-3-flash")

        # Should contain human message, not JSON wrapper
        assert "Analyze RELIANCE stock fundamentals" in ns
        assert "[m:" in ns
        assert "[s:" in ns
        assert "[c:" in ns  # Content hash present
        # Should NOT contain LangChain JSON metadata
        assert '"lc": 1' not in ns

    def test_namespace_prompt_different_system_prompts(self):
        """Different system prompts produce different cache keys."""
        from skopaq.llm.cache import _namespace_prompt
        import json

        def make_prompt(system: str, human: str) -> str:
            return json.dumps([
                {"lc": 1, "id": ["langchain", "schema", "messages", "SystemMessage"],
                 "kwargs": {"content": system, "type": "system"}},
                {"lc": 1, "id": ["langchain", "schema", "messages", "HumanMessage"],
                 "kwargs": {"content": human, "type": "human"}},
            ])

        ns1 = _namespace_prompt(make_prompt("You are a market analyst.", "Analyze RELIANCE"), "gemini")
        ns2 = _namespace_prompt(make_prompt("You are a news analyst.", "Analyze RELIANCE"), "gemini")
        assert ns1 != ns2  # Different system prompts → different keys

    def test_namespace_prompt_memory_change_invalidates_cache(self):
        """Agent memory changes must produce different cache keys.

        This is critical for the self-evolution loop: after a trade closes
        and the agent reflects (learns), the memory content injected deep
        in the prompt must cause a cache miss so the agent uses its new
        lessons instead of serving stale pre-learning responses.
        """
        from skopaq.llm.cache import _namespace_prompt

        # Simulate a long agent prompt where memories are appended at the end
        base = "You are a Bull Analyst. " + "A" * 500  # Role + market data
        no_memory = base + " No past reflections available."
        with_memory = base + " Past lessons: Avoid buying at all-time highs."

        ns1 = _namespace_prompt(no_memory, "gemini")
        ns2 = _namespace_prompt(with_memory, "gemini")

        # Content hash [c:] must differ even though first 300 chars are identical
        assert ns1 != ns2

    def test_namespace_prompt_same_content_same_key(self):
        """Identical prompts must produce identical cache keys (cache hit)."""
        from skopaq.llm.cache import _namespace_prompt

        prompt = "You are a Bull Analyst. " + "data " * 100
        ns1 = _namespace_prompt(prompt, "gemini")
        ns2 = _namespace_prompt(prompt, "gemini")
        assert ns1 == ns2

    def test_namespace_prompt_different_models(self):
        from skopaq.llm.cache import _namespace_prompt

        ns1 = _namespace_prompt("same prompt", "google:gemini-3-flash")
        ns2 = _namespace_prompt("same prompt", "anthropic:claude-opus-4-6")
        assert ns1 != ns2

    def test_namespace_prompt_truncates_long_prompts(self):
        from skopaq.llm.cache import _namespace_prompt, _MAX_PROMPT_LEN

        long_prompt = "A" * 5000
        ns = _namespace_prompt(long_prompt, "google:gemini-3-flash")
        assert len(ns) == _MAX_PROMPT_LEN

    def test_namespace_prompt_short_prompt_unchanged(self):
        from skopaq.llm.cache import _namespace_prompt, _model_hash, _MAX_PROMPT_LEN
        import hashlib

        short = "Analyze RELIANCE"
        ns = _namespace_prompt(short, "google:gemini-3-flash")
        content_hash = hashlib.sha256(short.encode()).hexdigest()[:8]
        expected = f"[m:{_model_hash('google:gemini-3-flash')}][c:{content_hash}] {short}"
        assert ns == expected
        assert len(ns) < _MAX_PROMPT_LEN


# ---------------------------------------------------------------------------
# CacheStats tests
# ---------------------------------------------------------------------------

class TestCacheStats:
    """Tests for the CacheStats dataclass."""

    def test_initial_values(self):
        from skopaq.llm.cache import CacheStats

        stats = CacheStats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.errors == 0
        assert stats.hit_rate_pct == 0.0

    def test_hit_rate_calculation(self):
        from skopaq.llm.cache import CacheStats

        stats = CacheStats(hits=3, misses=7)
        assert stats.hit_rate_pct == 30.0

    def test_hit_rate_all_hits(self):
        from skopaq.llm.cache import CacheStats

        stats = CacheStats(hits=10, misses=0)
        assert stats.hit_rate_pct == 100.0

    def test_reset(self):
        from skopaq.llm.cache import CacheStats

        stats = CacheStats(hits=5, misses=3, errors=1, store_count=8)
        stats.reset()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.errors == 0
        assert stats.store_count == 0


# ---------------------------------------------------------------------------
# LangCacheSemanticCache tests
# ---------------------------------------------------------------------------

class TestLangCacheSemanticCache:
    """Tests for the LangChain BaseCache implementation."""

    @patch("langcache.LangCache")
    def _make_cache(self, MockLangCache, threshold=0.90):
        """Create a cache instance with a mocked LangCache SDK client."""
        from skopaq.llm.cache import LangCacheSemanticCache

        mock_client = MagicMock()
        MockLangCache.return_value = mock_client

        cache = LangCacheSemanticCache(
            api_key="test-key",
            server_url="https://test.redis.io",
            cache_id="test-id",
            threshold=threshold,
        )
        return cache, mock_client

    def test_lookup_miss(self):
        """When SDK returns no match, lookup returns None."""
        cache, mock_client = self._make_cache()
        mock_client.search.return_value = None

        result = cache.lookup("What is RELIANCE's outlook?", "google:gemini-3-flash")

        assert result is None
        assert cache.stats.misses == 1
        assert cache.stats.hits == 0

    def test_lookup_hit(self):
        """When SDK returns a match, lookup returns deserialized Generations."""
        from skopaq.llm.cache import _serialize_generations

        cache, mock_client = self._make_cache()

        gens = _make_generations("Cached analysis result")
        # SDK returns SearchResponse(data=[CacheEntry(...)])
        mock_entry = MagicMock()
        mock_entry.response = _serialize_generations(gens)
        mock_entry.similarity = 0.95
        mock_result = MagicMock()
        mock_result.data = [mock_entry]
        mock_client.search.return_value = mock_result

        result = cache.lookup("What is RELIANCE's outlook?", "google:gemini-3-flash")

        assert result is not None
        assert len(result) == 1
        assert result[0].text == "Cached analysis result"
        assert cache.stats.hits == 1
        assert cache.stats.misses == 0

    def test_lookup_empty_data_list(self):
        """When SDK returns result with empty data list, treat as miss."""
        cache, mock_client = self._make_cache()

        mock_result = MagicMock()
        mock_result.data = []  # No entries above threshold
        mock_client.search.return_value = mock_result

        result = cache.lookup("prompt", "llm")

        assert result is None
        assert cache.stats.misses == 1

    def test_lookup_error_graceful(self):
        """When SDK raises an exception, lookup returns None (no crash)."""
        cache, mock_client = self._make_cache()
        mock_client.search.side_effect = ConnectionError("Network error")

        result = cache.lookup("prompt", "llm")

        assert result is None
        assert cache.stats.errors == 1

    def test_update_stores_correctly(self):
        """update() calls SDK set() with namespaced prompt (no attributes)."""
        from skopaq.llm.cache import _namespace_prompt

        cache, mock_client = self._make_cache()
        gens = _make_generations("Response to store")

        cache.update("What is RELIANCE?", "google:gemini-3-flash", gens)

        mock_client.set.assert_called_once()
        call_kwargs = mock_client.set.call_args
        expected_prompt = _namespace_prompt("What is RELIANCE?", "google:gemini-3-flash")
        assert call_kwargs.kwargs["prompt"] == expected_prompt
        assert "attributes" not in call_kwargs.kwargs
        assert cache.stats.store_count == 1

    def test_update_error_graceful(self):
        """When SDK set() raises, update() silently continues."""
        cache, mock_client = self._make_cache()
        mock_client.set.side_effect = RuntimeError("Storage error")

        # Should NOT raise
        cache.update("prompt", "llm", _make_generations())

        assert cache.stats.errors == 1

    def test_model_partitioning(self):
        """Different llm_string values produce different prompt namespaces."""
        from skopaq.llm.cache import _namespace_prompt

        cache, mock_client = self._make_cache()
        mock_client.search.return_value = None

        cache.lookup("same prompt", "google:gemini-3-flash")
        call1_prompt = mock_client.search.call_args.kwargs["prompt"]

        cache.lookup("same prompt", "anthropic:claude-opus-4-6")
        call2_prompt = mock_client.search.call_args.kwargs["prompt"]

        # Same prompt text but different models → different namespaced prompts
        assert call1_prompt != call2_prompt
        assert "same prompt" in call1_prompt
        assert "same prompt" in call2_prompt

    def test_clear_is_noop(self):
        """clear() does not raise or crash."""
        cache, _ = self._make_cache()
        cache.clear()  # Should not raise

    def test_stats_accumulate(self):
        """Stats accumulate across multiple operations."""
        from skopaq.llm.cache import _serialize_generations

        cache, mock_client = self._make_cache()

        # 2 misses
        mock_client.search.return_value = None
        cache.lookup("p1", "llm")
        cache.lookup("p2", "llm")

        # 1 hit — SDK returns SearchResponse(data=[CacheEntry(...)])
        mock_entry = MagicMock()
        mock_entry.response = _serialize_generations(_make_generations())
        mock_entry.similarity = 0.95
        mock_result = MagicMock()
        mock_result.data = [mock_entry]
        mock_client.search.return_value = mock_result
        cache.lookup("p3", "llm")

        # 1 store
        cache.update("p1", "llm", _make_generations())

        assert cache.stats.hits == 1
        assert cache.stats.misses == 2
        assert cache.stats.store_count == 1
        assert cache.stats.hit_rate_pct == pytest.approx(33.33, abs=0.1)


# ---------------------------------------------------------------------------
# init_langcache() factory tests
# ---------------------------------------------------------------------------

class TestInitLangcache:
    """Tests for the init_langcache() factory function."""

    def test_disabled_returns_none(self):
        from skopaq.llm.cache import init_langcache

        config = _make_config(enabled=False)
        assert init_langcache(config) is None

    def test_missing_api_key_returns_none(self):
        from skopaq.llm.cache import init_langcache

        config = _make_config(api_key="")
        assert init_langcache(config) is None

    def test_missing_server_url_returns_none(self):
        from skopaq.llm.cache import init_langcache

        config = _make_config(server_url="")
        assert init_langcache(config) is None

    def test_missing_cache_id_returns_none(self):
        from skopaq.llm.cache import init_langcache

        config = _make_config(cache_id="")
        assert init_langcache(config) is None

    @patch("langcache.LangCache")
    def test_success_returns_cache(self, MockLangCache):
        from skopaq.llm.cache import init_langcache

        config = _make_config()
        cache = init_langcache(config)

        assert cache is not None
        MockLangCache.assert_called_once_with(
            api_key="test-key",
            server_url="https://test.langcache.redis.io",
            cache_id="test-cache-id",
        )

    @patch("langcache.LangCache")
    def test_sdk_import_error_returns_none(self, MockLangCache):
        from skopaq.llm.cache import init_langcache

        MockLangCache.side_effect = ImportError("No module named 'langcache'")
        config = _make_config()

        assert init_langcache(config) is None

    @patch("langcache.LangCache")
    def test_threshold_passed_correctly(self, MockLangCache):
        from skopaq.llm.cache import init_langcache, LangCacheSemanticCache

        config = _make_config(threshold=0.85)
        cache = init_langcache(config)

        assert cache is not None
        assert cache._threshold == 0.85


# ---------------------------------------------------------------------------
# LangChain integration test (set_llm_cache compatibility)
# ---------------------------------------------------------------------------

class TestLangChainIntegration:
    """Verify our cache is accepted by LangChain's set_llm_cache()."""

    @patch("langcache.LangCache")
    def test_set_llm_cache_accepts_our_cache(self, MockLangCache):
        from langchain_core.globals import set_llm_cache, get_llm_cache
        from skopaq.llm.cache import LangCacheSemanticCache

        cache = LangCacheSemanticCache(
            api_key="k",
            server_url="https://test.redis.io",
            cache_id="id",
        )

        # Should not raise — proves our class satisfies the BaseCache interface
        set_llm_cache(cache)
        assert get_llm_cache() is cache

        # Clean up global state
        set_llm_cache(None)

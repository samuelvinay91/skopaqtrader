"""Live integration test for Redis LangCache semantic caching.

Requires real credentials in environment:
    SKOPAQ_LANGCACHE_API_KEY
    SKOPAQ_LANGCACHE_SERVER_URL
    SKOPAQ_LANGCACHE_CACHE_ID

Run with::

    python -m pytest tests/integration/test_langcache_live.py -v -s
"""

import os
import time

import pytest

from langchain_core.outputs import Generation


pytestmark = pytest.mark.integration


def _has_langcache_creds() -> bool:
    """Check if all LangCache credentials are available."""
    return all([
        os.getenv("SKOPAQ_LANGCACHE_API_KEY"),
        os.getenv("SKOPAQ_LANGCACHE_SERVER_URL"),
        os.getenv("SKOPAQ_LANGCACHE_CACHE_ID"),
    ])


@pytest.fixture
def live_cache():
    """Create a real LangCacheSemanticCache connected to Redis Cloud."""
    from skopaq.llm.cache import LangCacheSemanticCache

    cache = LangCacheSemanticCache(
        api_key=os.environ["SKOPAQ_LANGCACHE_API_KEY"],
        server_url=os.environ["SKOPAQ_LANGCACHE_SERVER_URL"],
        cache_id=os.environ["SKOPAQ_LANGCACHE_CACHE_ID"],
        threshold=0.85,  # Slightly lenient for testing
    )
    yield cache


@pytest.fixture
def unique_prompt():
    """Generate a unique prompt to avoid cross-test contamination."""
    return f"Integration test prompt {time.time_ns()}: Analyze RELIANCE stock fundamentals"


@pytest.mark.skipif(
    not _has_langcache_creds(),
    reason="SKOPAQ_LANGCACHE_* credentials not set",
)
class TestLangCacheLive:
    """End-to-end tests against the real Redis LangCache service."""

    def test_store_and_retrieve_exact(self, live_cache, unique_prompt):
        """Store a response and retrieve it with the exact same prompt."""
        llm_string = "test:integration-model"
        response = [Generation(text="RELIANCE looks bullish", generation_info={"test": True})]

        # Store
        live_cache.update(unique_prompt, llm_string, response)

        # Small delay for eventual consistency
        time.sleep(0.5)

        # Retrieve — exact same prompt should hit
        result = live_cache.lookup(unique_prompt, llm_string)

        assert result is not None, "Expected cache HIT for exact same prompt"
        assert len(result) == 1
        assert result[0].text == "RELIANCE looks bullish"
        assert live_cache.stats.hits >= 1

    def test_miss_for_different_prompt(self, live_cache):
        """Completely different prompt should be a cache miss."""
        llm_string = "test:integration-model"
        unrelated = f"Unrelated weather query {time.time_ns()}"

        result = live_cache.lookup(unrelated, llm_string)
        assert result is None, "Expected cache MISS for unrelated prompt"

    def test_miss_for_different_model(self, live_cache, unique_prompt):
        """Same prompt but different model partition should miss."""
        response = [Generation(text="Model A response")]

        # Store under model A
        live_cache.update(unique_prompt, "model-a:v1", response)
        time.sleep(0.5)

        # Lookup under model B — should miss due to different partition
        result = live_cache.lookup(unique_prompt, "model-b:v1")
        assert result is None, "Expected cache MISS for different model partition"

    def test_stats_tracking(self, live_cache, unique_prompt):
        """Verify stats counters increment correctly during live operations."""
        llm_string = "test:stats-model"

        # Miss
        live_cache.lookup(f"unknown-{time.time_ns()}", llm_string)
        assert live_cache.stats.misses >= 1

        # Store
        live_cache.update(unique_prompt, llm_string, [Generation(text="stats test")])
        assert live_cache.stats.store_count >= 1

        # Timing tracked
        assert live_cache.stats.total_lookup_ms > 0
        assert live_cache.stats.total_store_ms > 0

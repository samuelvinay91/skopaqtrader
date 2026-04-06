"""Semantic LLM cache backed by Redis Cloud LangCache.

Implements LangChain's ``BaseCache`` interface so it can be activated
globally via ``set_llm_cache()`` — transparently caching every
``BaseChatModel.generate()`` call without any agent code changes.

Usage::

    from skopaq.llm.cache import init_langcache
    from langchain_core.globals import set_llm_cache

    cache = init_langcache(config)
    if cache:
        set_llm_cache(cache)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from langchain_core.caches import BaseCache, RETURN_VAL_TYPE
from langchain_core.outputs import Generation

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stats tracking
# ---------------------------------------------------------------------------

@dataclass
class CacheStats:
    """In-memory counters for cache performance monitoring."""

    hits: int = 0
    misses: int = 0
    errors: int = 0
    store_count: int = 0
    total_lookup_ms: float = 0.0
    total_store_ms: float = 0.0

    @property
    def hit_rate_pct(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    def reset(self) -> None:
        self.hits = 0
        self.misses = 0
        self.errors = 0
        self.store_count = 0
        self.total_lookup_ms = 0.0
        self.total_store_ms = 0.0


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _serialize_generations(generations: RETURN_VAL_TYPE) -> str:
    """Serialize a list of Generation objects to JSON string."""
    return json.dumps(
        [{"text": g.text, "info": g.generation_info} for g in generations]
    )


def _deserialize_generations(data: str) -> RETURN_VAL_TYPE:
    """Deserialize JSON string back to a list of Generation objects."""
    items = json.loads(data)
    return [
        Generation(text=item["text"], generation_info=item.get("info"))
        for item in items
    ]


def _model_hash(llm_string: str) -> str:
    """Produce a short hash of the LLM identifier for cache partitioning.

    This prevents cross-model contamination — e.g. a Gemini response
    being served for a Claude query.
    """
    return hashlib.sha256(llm_string.encode()).hexdigest()[:16]


# Redis LangCache limits (discovered empirically):
# 1. SDK client-side validation: 1024 chars
# 2. Server character limit: ~600 chars
# 3. Embedding model token limit: 128 tokens
# At ~3.8 chars/token, 128 tokens ≈ 490 chars.  Use 350 for margin.
_MAX_PROMPT_LEN = 350

# Response bodies over ~99 KB trigger 413 Payload Too Large.
_MAX_RESPONSE_BYTES = 95_000


def _extract_content(prompt: str) -> tuple[str, str]:
    """Extract human message content and system prompt from LangChain's serialized prompt.

    LangChain's ``BaseChatModel`` serializes messages as JSON::

        [{"lc": 1, "type": "constructor",
          "id": ["langchain", "schema", "messages", "HumanMessage"],
          "kwargs": {"content": "Analyze RELIANCE", "type": "human"}}]

    Returns ``(human_content, system_content)`` — both empty strings if
    parsing fails (falls back gracefully).
    """
    try:
        messages = json.loads(prompt)
        if not isinstance(messages, list):
            return "", ""

        human = ""
        system = ""
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            kwargs = msg.get("kwargs", {})
            content = kwargs.get("content", "")
            msg_id = str(msg.get("id", []))
            msg_type = kwargs.get("type", "")

            if "HumanMessage" in msg_id or msg_type == "human":
                human = content  # Keep last human message
            elif "SystemMessage" in msg_id or msg_type == "system":
                system = content

        return human, system
    except (json.JSONDecodeError, TypeError, KeyError):
        return "", ""


def _namespace_prompt(prompt: str, llm_string: str) -> str:
    """Build a cache key from a LangChain serialized prompt.

    Strategy:
    1. Extract the human message content (the actual query) and system
       prompt from LangChain's JSON-serialized messages.
    2. Build a prefix with model hash + system prompt hash + a content
       hash of the FULL human message — this prevents:
       - Cross-model contamination (``[m:]``)
       - Cross-agent contamination (``[s:]``)
       - Stale cache hits after memory/learning updates (``[c:]``)
    3. Append the human message content, truncated to fit within the
       embedding model's 128-token limit.

    The ``[c:]`` content hash is critical for the memory-augmented agent
    memory system: agent memories (past lessons from reflections) are
    injected deep inside the human message.  Without this hash, the
    truncated cache key would be identical before and after learning,
    serving stale pre-learning responses.

    If the prompt isn't valid LangChain JSON (e.g. in unit tests),
    falls back to simple truncation of the raw prompt.
    """
    model_tag = _model_hash(llm_string)
    human, system = _extract_content(prompt)

    if human:
        # Hash the system prompt so different agents don't share cache
        sys_tag = hashlib.sha256(system.encode()).hexdigest()[:8] if system else "nosys"
        # Hash the FULL human content so memory/data changes invalidate cache
        content_tag = hashlib.sha256(human.encode()).hexdigest()[:8]
        prefix = f"[m:{model_tag}][s:{sys_tag}][c:{content_tag}] "
        remaining = _MAX_PROMPT_LEN - len(prefix)
        return prefix + human[:remaining]

    # Fallback: raw prompt (unit tests, non-chat models)
    content_tag = hashlib.sha256(prompt.encode()).hexdigest()[:8]
    prefix = f"[m:{model_tag}][c:{content_tag}] "
    remaining = _MAX_PROMPT_LEN - len(prefix)
    return prefix + prompt[:remaining]


# ---------------------------------------------------------------------------
# LangChain BaseCache implementation
# ---------------------------------------------------------------------------

class LangCacheSemanticCache(BaseCache):
    """Semantic LLM cache using Redis Cloud LangCache service.

    Each prompt is embedded server-side and matched against cached
    prompts using cosine similarity.  Responses are partitioned by
    model (via the ``llm_string`` hash) to prevent cross-model hits.

    All errors are caught and logged — the cache never blocks or
    raises.  On failure, ``lookup()`` returns ``None`` (cache miss)
    and ``update()`` silently continues.
    """

    def __init__(
        self,
        *,
        api_key: str,
        server_url: str,
        cache_id: str,
        threshold: float = 0.90,
    ) -> None:
        from langcache import LangCache

        self._client = LangCache(
            api_key=api_key,
            server_url=server_url,
            cache_id=cache_id,
        )
        self._threshold = threshold
        self._stats = CacheStats()

    # -- BaseCache interface ------------------------------------------------

    def lookup(self, prompt: str, llm_string: str) -> Optional[RETURN_VAL_TYPE]:
        """Check cache for a semantically similar prompt.

        Returns cached ``Generation`` list on hit, ``None`` on miss.

        The SDK ``search()`` returns ``SearchResponse(data=[CacheEntry(...)])``
        where each ``CacheEntry`` has ``response``, ``similarity``, etc.
        An empty ``data`` list means no match above the threshold.
        """
        namespaced = _namespace_prompt(prompt, llm_string)
        t0 = time.monotonic()
        try:
            result = self._client.search(
                prompt=namespaced,
                similarity_threshold=self._threshold,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._stats.total_lookup_ms += elapsed_ms

            # result.data is a list of CacheEntry; non-empty = hit
            if result and result.data:
                best = result.data[0]  # Highest similarity match
                self._stats.hits += 1
                logger.debug(
                    "Cache HIT (%.1fms, sim=%.3f, model=%s)",
                    elapsed_ms, best.similarity, _model_hash(llm_string)[:8],
                )
                return _deserialize_generations(best.response)

            self._stats.misses += 1
            logger.debug("Cache MISS (%.1fms)", elapsed_ms)
            return None

        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._stats.total_lookup_ms += elapsed_ms
            self._stats.errors += 1
            # Log concisely — full tracebacks are noisy for expected failures
            # (e.g. Upstash down, rate limited)
            logger.debug("Cache lookup error (%.1fms): %s", elapsed_ms, exc)
            return None

    def update(self, prompt: str, llm_string: str, return_val: RETURN_VAL_TYPE) -> None:
        """Store an LLM response in the cache."""
        namespaced = _namespace_prompt(prompt, llm_string)
        t0 = time.monotonic()
        try:
            serialized = _serialize_generations(return_val)

            # Skip caching responses that exceed the server's payload limit
            if len(serialized.encode()) > _MAX_RESPONSE_BYTES:
                logger.debug(
                    "Response too large for cache (%d bytes > %d limit) — skipping",
                    len(serialized.encode()), _MAX_RESPONSE_BYTES,
                )
                return

            self._client.set(
                prompt=namespaced,
                response=serialized,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._stats.total_store_ms += elapsed_ms
            self._stats.store_count += 1
            logger.debug(
                "Cache STORE (%.1fms, %d chars)",
                elapsed_ms, len(serialized),
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._stats.total_store_ms += elapsed_ms
            self._stats.errors += 1
            logger.debug("Cache store error (%.1fms): %s", elapsed_ms, exc)

    def clear(self, **kwargs: Any) -> None:
        """No-op — the managed service handles eviction/TTL."""
        pass

    # -- Convenience --------------------------------------------------------

    @property
    def stats(self) -> CacheStats:
        return self._stats


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _make_in_memory_cache() -> BaseCache:
    """Create LangChain's built-in InMemoryCache as a fallback.

    Provides exact-match caching within the current process — no external
    dependencies.  Useful for avoiding redundant LLM calls within a single
    session (e.g. agent retries, repeated slash commands).
    """
    from langchain_core.caches import InMemoryCache

    logger.info("Using in-memory LLM cache (exact-match, session-scoped)")
    return InMemoryCache()


def init_langcache(config: Any) -> Optional[BaseCache]:
    """Create the best available LLM cache from SkopaqConfig.

    Priority:
    1. **LangCache semantic cache** (Upstash Redis) — if enabled and
       credentials are present.
    2. **In-memory cache** — always available, zero config.  Provides
       exact-match caching within the current process.

    Returns ``None`` only when ``langcache_enabled`` is explicitly
    ``False`` **and** the caller doesn't want any cache.
    """
    if not getattr(config, "langcache_enabled", False):
        # Even when the semantic cache is disabled, provide in-memory
        # caching so repeated identical prompts don't cost extra.
        return _make_in_memory_cache()

    api_key = ""
    if hasattr(config, "langcache_api_key"):
        api_key = config.langcache_api_key.get_secret_value()

    server_url = getattr(config, "langcache_server_url", "")
    cache_id = getattr(config, "langcache_cache_id", "")

    if not api_key or not server_url or not cache_id:
        logger.debug(
            "LangCache credentials incomplete — falling back to in-memory "
            "(url=%s, cache_id=%s, key=%s)",
            bool(server_url), bool(cache_id), bool(api_key),
        )
        return _make_in_memory_cache()

    try:
        cache = LangCacheSemanticCache(
            api_key=api_key,
            server_url=server_url,
            cache_id=cache_id,
            threshold=getattr(config, "langcache_threshold", 0.90),
        )
        logger.info(
            "LangCache semantic cache initialised (threshold=%.2f, server=%s)",
            cache._threshold, server_url,
        )
        return cache
    except Exception:
        logger.warning(
            "Failed to initialise LangCache — falling back to in-memory cache",
            exc_info=True,
        )
        return _make_in_memory_cache()

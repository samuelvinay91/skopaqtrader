"""Integration test — Multi-model scanner with Gemini + Perplexity Sonar + Grok.

Tests the full multi-model scanner pipeline:
    1. Fetch real quotes from INDstocks API
    2. Technical screening with Gemini Flash (always runs)
    3. News screening with Perplexity Sonar via OpenRouter (parallel)
    4. Social screening with Grok via OpenRouter (parallel)
    5. Deduplication merges multi-source signals

Requires: SKOPAQ_INDSTOCKS_TOKEN, GOOGLE_API_KEY, OPENROUTER_API_KEY in .env

Run:  python3 -m pytest tests/integration/test_scanner_multimodel.py -v -m integration -s
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import pytest
from dotenv import load_dotenv

load_dotenv(override=True)

pytestmark = pytest.mark.integration

logger = logging.getLogger(__name__)


# ── Skip helpers ──────────────────────────────────────────────────────

def _skip_unless_full_stack():
    """Skip if any required key is missing."""
    if not os.environ.get("SKOPAQ_INDSTOCKS_TOKEN"):
        pytest.skip("SKOPAQ_INDSTOCKS_TOKEN not set")
    if not os.environ.get("GOOGLE_API_KEY"):
        pytest.skip("GOOGLE_API_KEY not set")
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")


def _skip_unless_openrouter():
    """Skip if OpenRouter key is missing."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")


# ── Screener callables ────────────────────────────────────────────────

async def gemini_flash_screener(prompt: str) -> str:
    """Send technical screening prompt to Gemini 3 Flash."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    from skopaq.llm import extract_text

    llm = ChatGoogleGenerativeAI(
        model="gemini-3-flash-preview",
        temperature=0.1,
        max_output_tokens=2048,
    )
    response = await llm.ainvoke(prompt)
    return extract_text(response.content)


async def perplexity_news_screener(prompt: str) -> str:
    """Send news screening prompt to Perplexity Sonar via OpenRouter.

    Perplexity Sonar is web-grounded — it searches the web in real time
    to find breaking news and event-driven catalysts.
    """
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model="perplexity/sonar-pro",
        openai_api_key=os.environ["OPENROUTER_API_KEY"],
        openai_api_base="https://openrouter.ai/api/v1",
        temperature=0.1,
        max_tokens=2048,
    )
    response = await llm.ainvoke(prompt)
    return response.content


async def grok_social_screener(prompt: str) -> str:
    """Send social sentiment prompt to Grok via OpenRouter.

    Grok has X/Twitter integration — it can detect retail sentiment shifts
    and trending discussions about stocks.
    """
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model="x-ai/grok-3-mini",
        openai_api_key=os.environ["OPENROUTER_API_KEY"],
        openai_api_base="https://openrouter.ai/api/v1",
        temperature=0.1,
        max_tokens=2048,
    )
    response = await llm.ainvoke(prompt)
    return response.content


# ── Reuse quote fetcher from the E2E test ─────────────────────────────
# Import the already-verified quote fetcher to avoid duplication
from tests.integration.test_scanner_e2e import indstocks_quote_fetcher


# ── Test symbols ──────────────────────────────────────────────────────

MULTIMODEL_WATCHLIST = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "SBIN", "BAJFINANCE", "LT", "BHARTIARTL", "ITC",
]


# ── Tests: Individual screeners ───────────────────────────────────────

class TestPerplexityNewsScreener:
    """Test Perplexity Sonar news screening independently."""

    def test_returns_json_response(self):
        """Perplexity Sonar should return valid JSON candidates for Indian stocks."""
        _skip_unless_openrouter()
        from skopaq.scanner.screen import build_news_prompt, parse_screen_response

        symbols = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]
        prompt = build_news_prompt(symbols, max_candidates=3)

        print(f"\n  News prompt ({len(prompt)} chars):")
        print(f"  {prompt[:200]}...")

        response = asyncio.run(perplexity_news_screener(prompt))
        print(f"\n  Perplexity Sonar response:\n  {response[:500]}")

        candidates = parse_screen_response(response)
        print(f"\n  Parsed {len(candidates)} news candidates:")
        for c in candidates:
            print(f"    {c.symbol}: {c.reason} (urgency={c.urgency})")

        # Should return valid JSON (may be empty if no breaking news)
        assert isinstance(candidates, list)
        # Verify any returned candidates have valid structure
        for c in candidates:
            assert c.symbol, "News candidate missing symbol"
            assert c.reason, "News candidate missing reason"
            assert c.urgency in ("high", "normal"), f"Invalid urgency: {c.urgency}"


class TestGrokSocialScreener:
    """Test Grok social sentiment screening independently."""

    def test_returns_json_response(self):
        """Grok should return valid JSON candidates for social signals."""
        _skip_unless_openrouter()
        from skopaq.scanner.screen import build_social_prompt, parse_screen_response

        symbols = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]
        prompt = build_social_prompt(symbols, max_candidates=3)

        print(f"\n  Social prompt ({len(prompt)} chars):")
        print(f"  {prompt[:200]}...")

        response = asyncio.run(grok_social_screener(prompt))
        print(f"\n  Grok response:\n  {response[:500]}")

        candidates = parse_screen_response(response)
        print(f"\n  Parsed {len(candidates)} social candidates:")
        for c in candidates:
            print(f"    {c.symbol}: {c.reason} (urgency={c.urgency})")

        # Should return valid JSON (may be empty if no social signals)
        assert isinstance(candidates, list)
        for c in candidates:
            assert c.symbol, "Social candidate missing symbol"
            assert c.reason, "Social candidate missing reason"
            assert c.urgency in ("high", "normal"), f"Invalid urgency: {c.urgency}"


# ── Tests: Full multi-model scanner ──────────────────────────────────

class TestMultiModelScanner:
    """End-to-end: INDstocks quotes → Gemini + Perplexity + Grok → merged candidates."""

    def test_scan_once_all_three_screeners(self):
        """Full multi-model scan with all three LLMs running in parallel."""
        _skip_unless_full_stack()
        from skopaq.scanner.engine import ScannerEngine
        from skopaq.scanner.watchlist import Watchlist

        watchlist = Watchlist(symbols=MULTIMODEL_WATCHLIST)

        engine = ScannerEngine(
            watchlist=watchlist,
            max_candidates=5,
            quote_fetcher=indstocks_quote_fetcher,
            llm_screener=gemini_flash_screener,
            news_screener=perplexity_news_screener,
            social_screener=grok_social_screener,
        )

        # Verify all 3 screeners are active
        info = engine._screener_info()
        assert info["count"] == 3
        assert set(info["active"]) == {"technical", "news", "social"}

        candidates = asyncio.run(engine.scan_once())

        print(f"\n  Multi-model scanner produced {len(candidates)} candidates:")
        for c in candidates:
            source = c.metrics.get("source", "?")
            print(f"    [{source}] {c.symbol}: {c.reason} (urgency={c.urgency})")

        # Check deduplication metadata
        multi_source = [c for c in candidates if c.metrics.get("source") == "multi"]
        if multi_source:
            print(f"\n  Multi-source confluence ({len(multi_source)} candidates):")
            for c in multi_source:
                print(f"    {c.symbol}: sources={c.metrics.get('sources')}")

        assert isinstance(candidates, list)
        assert engine._cycle_count == 1
        print(f"\n  Engine status: {engine.status}")

    def test_scan_degrades_gracefully_on_screener_failure(self):
        """If one screener fails, others should still produce candidates."""
        _skip_unless_full_stack()
        from skopaq.scanner.engine import ScannerEngine
        from skopaq.scanner.watchlist import Watchlist

        async def failing_screener(prompt: str) -> str:
            raise RuntimeError("Simulated screener failure")

        watchlist = Watchlist(symbols=["RELIANCE", "TCS", "HDFCBANK"])

        engine = ScannerEngine(
            watchlist=watchlist,
            max_candidates=3,
            quote_fetcher=indstocks_quote_fetcher,
            llm_screener=gemini_flash_screener,      # Real — should work
            news_screener=failing_screener,            # Will fail
            social_screener=grok_social_screener,      # Real — should work
        )

        candidates = asyncio.run(engine.scan_once())

        print(f"\n  Degraded scan produced {len(candidates)} candidates:")
        for c in candidates:
            source = c.metrics.get("source", "?")
            print(f"    [{source}] {c.symbol}: {c.reason}")

        # Pipeline shouldn't crash — technical + social should still work
        assert isinstance(candidates, list)
        # No news-sourced candidates (that screener failed)
        news_candidates = [c for c in candidates if c.metrics.get("source") == "news"]
        assert len(news_candidates) == 0, "Failed news screener shouldn't produce candidates"

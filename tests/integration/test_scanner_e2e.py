"""Integration test — Scanner engine with real INDstocks data + real Gemini Flash.

Tests the full scanner cycle:
    1. Fetch real quotes from INDstocks API
    2. Compute metrics (change%, volume ratio, gap%)
    3. Send to Gemini Flash for candidate selection
    4. Parse LLM response into ScannerCandidate objects

Requires: SKOPAQ_INDSTOCKS_TOKEN and GOOGLE_API_KEY in .env

Run:  python3 -m pytest tests/integration/test_scanner_e2e.py -v -m integration -s
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
from typing import Any

import pytest
from dotenv import load_dotenv

load_dotenv(override=True)

pytestmark = pytest.mark.integration

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────

def _skip_unless_ready():
    """Skip if either INDstocks token or Google API key is missing."""
    if not os.environ.get("SKOPAQ_INDSTOCKS_TOKEN"):
        pytest.skip("SKOPAQ_INDSTOCKS_TOKEN not set")
    if not os.environ.get("GOOGLE_API_KEY"):
        pytest.skip("GOOGLE_API_KEY not set")


def _get_client():
    """Create a one-shot INDstocks REST client."""
    from skopaq.config import SkopaqConfig
    from skopaq.broker.client import INDstocksClient
    from skopaq.broker.token_manager import TokenManager

    config = SkopaqConfig()
    token_mgr = TokenManager()
    return INDstocksClient(config, token_mgr)


# ── Instrument resolution cache (shared across test methods) ──────────

_scrip_cache: dict[str, str] = {}


async def _resolve_scrip_codes(symbols: list[str]) -> dict[str, str]:
    """Resolve a batch of trading symbols to scrip-codes.

    Downloads the instruments CSV once and caches it for the test session.
    Returns: ``{"RELIANCE": "NSE_2885", "TCS": "NSE_11536", ...}``
    """
    global _scrip_cache

    # If cache is populated and covers all symbols, skip CSV download
    missing = [s for s in symbols if s not in _scrip_cache]
    if not missing and _scrip_cache:
        return {s: _scrip_cache[s] for s in symbols if s in _scrip_cache}

    # Download instruments CSV
    client = _get_client()
    async with client:
        csv_text = await client.get_instruments(source="equity")

    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        exch = row.get("EXCH", "").strip()
        trading_symbol = row.get("TRADING_SYMBOL", "").strip()
        security_id = row.get("SECURITY_ID", "").strip()
        if exch == "NSE" and trading_symbol and security_id:
            _scrip_cache[trading_symbol] = f"NSE_{security_id}"

    return {s: _scrip_cache[s] for s in symbols if s in _scrip_cache}


# ── Quote Fetcher (wires INDstocks to scanner interface) ──────────────

async def indstocks_quote_fetcher(symbols: list[str]) -> list[dict[str, Any]]:
    """Fetch real quotes from INDstocks and return dicts for the scanner.

    The scanner expects dicts with keys:
        symbol, ltp, open, high, low, close, volume, avg_volume
    """
    # Step 1: Resolve symbols to scrip-codes
    mapping = await _resolve_scrip_codes(symbols)
    if not mapping:
        logger.warning("No symbols resolved to scrip-codes")
        return []

    resolved_symbols = list(mapping.keys())
    scrip_codes = [mapping[s] for s in resolved_symbols]

    # Step 2: Batch-fetch quotes
    client = _get_client()
    async with client:
        quotes = await client.get_quotes(
            scrip_codes=scrip_codes,
            symbols=resolved_symbols,
        )

    # Step 3: Convert Quote objects to dicts for the scanner
    result = []
    for q in quotes:
        result.append({
            "symbol": q.symbol,
            "ltp": q.ltp,
            "open": q.open,
            "high": q.high,
            "low": q.low,
            "close": q.close,      # prev_close from API
            "volume": q.volume,
            "avg_volume": q.volume,  # Use today's volume as proxy (no avg in API)
        })

    return result


# ── LLM Screener (wires Gemini Flash to scanner interface) ────────────

async def gemini_flash_screener(prompt: str) -> str:
    """Send the screening prompt to Gemini 3 Flash and return the response."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    from skopaq.llm import extract_text

    llm = ChatGoogleGenerativeAI(
        model="gemini-3-flash-preview",
        temperature=0.1,   # Low but not zero — allow some variation
        max_output_tokens=2048,
    )
    response = await llm.ainvoke(prompt)
    return extract_text(response.content)


# ── Tests ──────────────────────────────────────────────────────────────

# Small watchlist for testing (avoid hitting rate limits with all 51 NIFTY stocks)
TEST_WATCHLIST = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]


class TestQuoteFetcher:
    """Test the quote fetcher wiring independently."""

    def test_resolves_scrip_codes(self):
        """Verify that symbols resolve to scrip-codes."""
        _skip_unless_ready()
        mapping = asyncio.run(_resolve_scrip_codes(TEST_WATCHLIST))

        print(f"\n  Resolved {len(mapping)} symbols:")
        for sym, code in mapping.items():
            print(f"    {sym} → {code}")

        assert len(mapping) >= 3, f"Only resolved {len(mapping)}/{len(TEST_WATCHLIST)}"
        # RELIANCE should always be NSE_2885
        assert mapping.get("RELIANCE", "").startswith("NSE_"), "RELIANCE not resolved"

    def test_fetches_real_quotes(self):
        """Verify that quote fetcher returns well-formed dicts."""
        _skip_unless_ready()
        quotes = asyncio.run(indstocks_quote_fetcher(TEST_WATCHLIST))

        print(f"\n  Fetched {len(quotes)} quotes:")
        for q in quotes:
            print(f"    {q['symbol']}: LTP={q['ltp']}, Vol={q['volume']}")

        assert len(quotes) >= 3, f"Only got {len(quotes)} quotes"
        for q in quotes:
            assert q["symbol"], "Empty symbol"
            assert q["ltp"] > 0, f"{q['symbol']} has LTP={q['ltp']}"
            assert "volume" in q


class TestLlmScreener:
    """Test the LLM screener wiring independently."""

    def test_gemini_returns_json(self):
        """Verify Gemini Flash can parse metrics and return JSON candidates."""
        _skip_unless_ready()
        from skopaq.scanner.screen import build_screen_prompt
        from skopaq.scanner.models import ScannerMetrics

        # Build a small metrics list
        metrics = [
            ScannerMetrics(symbol="RELIANCE", ltp=1361, change_pct=-2.34,
                          volume=6_400_000, volume_ratio=1.8, gap_pct=-0.5),
            ScannerMetrics(symbol="TCS", ltp=3800, change_pct=1.20,
                          volume=2_100_000, volume_ratio=2.5, gap_pct=0.8),
            ScannerMetrics(symbol="HDFCBANK", ltp=1780, change_pct=0.10,
                          volume=4_500_000, volume_ratio=0.9, gap_pct=0.1),
        ]

        prompt = build_screen_prompt(metrics, max_candidates=2)
        print(f"\n  Prompt ({len(prompt)} chars):")
        print(f"  {prompt[:200]}...")

        response = asyncio.run(gemini_flash_screener(prompt))
        print(f"\n  Gemini response:\n  {response}")

        # Should be parseable JSON
        from skopaq.scanner.screen import parse_screen_response
        candidates = parse_screen_response(response)
        print(f"\n  Parsed {len(candidates)} candidates:")
        for c in candidates:
            print(f"    {c.symbol}: {c.reason} (urgency={c.urgency})")

        # Gemini should return valid JSON (even if empty array)
        assert isinstance(candidates, list), "parse_screen_response returned non-list"


class TestScannerE2E:
    """End-to-end: real INDstocks quotes → real Gemini Flash → candidates."""

    def test_scan_once_produces_candidates(self):
        """Full scan cycle with real data and real LLM."""
        _skip_unless_ready()
        from skopaq.scanner.engine import ScannerEngine
        from skopaq.scanner.watchlist import Watchlist

        # Use small watchlist
        watchlist = Watchlist(symbols=TEST_WATCHLIST)

        engine = ScannerEngine(
            watchlist=watchlist,
            max_candidates=3,
            quote_fetcher=indstocks_quote_fetcher,
            llm_screener=gemini_flash_screener,
        )

        candidates = asyncio.run(engine.scan_once())

        print(f"\n  Scanner produced {len(candidates)} candidates:")
        for c in candidates:
            print(f"    {c.symbol}: {c.reason} (urgency={c.urgency})")

        # With real data, Gemini should parse and respond
        # (may return 0 candidates if market is calm — that's OK)
        assert isinstance(candidates, list)
        assert engine._cycle_count == 1
        assert engine._last_cycle_at is not None
        print(f"  Cycle count: {engine._cycle_count}")
        print(f"  Last cycle: {engine._last_cycle_at.isoformat()}")

    def test_scan_once_full_nifty(self):
        """Scan with a larger subset of NIFTY stocks (10 stocks)."""
        _skip_unless_ready()
        from skopaq.scanner.engine import ScannerEngine
        from skopaq.scanner.watchlist import Watchlist

        # Larger watchlist — still not all 51 to keep API calls reasonable
        symbols = [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
            "SBIN", "BAJFINANCE", "LT", "BHARTIARTL", "ITC",
        ]
        watchlist = Watchlist(symbols=symbols)

        engine = ScannerEngine(
            watchlist=watchlist,
            max_candidates=5,
            quote_fetcher=indstocks_quote_fetcher,
            llm_screener=gemini_flash_screener,
        )

        candidates = asyncio.run(engine.scan_once())

        print(f"\n  Scanner (10 stocks) produced {len(candidates)} candidates:")
        for c in candidates:
            print(f"    {c.symbol}: {c.reason} (urgency={c.urgency})")

        assert isinstance(candidates, list)
        # With 10 real stocks, we'd expect at least some LLM output
        # but market conditions vary, so we just check the pipeline didn't crash
        print(f"  Engine status: {engine.status}")

"""LLM-based screening — multi-model prompts for candidate selection.

Supports three screening modes:

- **technical** (Gemini Flash): Price/volume metrics analysis
- **news** (Perplexity Sonar): Breaking news and event-driven signals
- **social** (Grok): Social media sentiment and retail buzz

Each mode produces ``ScannerCandidate`` objects with a ``source`` tag in
the metrics dict so downstream systems know which model flagged it.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from skopaq.scanner.models import ScannerCandidate, ScannerMetrics

logger = logging.getLogger(__name__)

# ── Prompt Templates ──────────────────────────────────────────────────

SCREEN_PROMPT_TEMPLATE = """\
You are a stock screener for the Indian equity market (NSE).
Analyze the following NIFTY stocks and identify up to {max_candidates} \
candidates that show the strongest trading signals RIGHT NOW.

For each candidate, provide:
- symbol: the stock symbol
- reason: one-line explanation (max 100 chars)
- urgency: "high" or "normal"

Return ONLY valid JSON — an array of objects.  No markdown, no explanation.
If no stocks are interesting, return an empty array [].

Current market metrics:
{metrics_table}

Respond with JSON only:
"""

NEWS_SCREEN_PROMPT_TEMPLATE = """\
You are a financial news analyst for the Indian equity market (NSE).
For the stocks below, identify up to {max_candidates} that have \
ACTIONABLE breaking news, earnings surprises, regulatory changes, \
or event-driven catalysts happening RIGHT NOW or in the last 24 hours.

For each candidate, provide:
- symbol: the stock symbol
- reason: one-line explanation of the NEWS event (max 100 chars)
- urgency: "high" if event is breaking/imminent, "normal" otherwise

Return ONLY valid JSON — an array of objects.  No markdown, no explanation.
If no stocks have newsworthy events, return an empty array [].

Stocks to check: {symbols}

Respond with JSON only:
"""

SOCIAL_SCREEN_PROMPT_TEMPLATE = """\
You are a social media sentiment analyst for the Indian equity market (NSE).
For the stocks below, identify up to {max_candidates} that show \
unusual social media activity, retail sentiment shifts, or trending \
discussions on Twitter/X, Reddit, or financial forums.

For each candidate, provide:
- symbol: the stock symbol
- reason: one-line explanation of the SOCIAL signal (max 100 chars)
- urgency: "high" if momentum is accelerating, "normal" otherwise

Return ONLY valid JSON — an array of objects.  No markdown, no explanation.
If no stocks have notable social signals, return an empty array [].

Stocks to check: {symbols}

Respond with JSON only:
"""


def format_metrics_table(metrics_list: list[ScannerMetrics]) -> str:
    """Format scanner metrics as a compact table for the LLM prompt."""
    lines = ["Symbol      | Change% | VolRatio | Gap%"]
    lines.append("-" * 45)
    for m in metrics_list:
        lines.append(
            f"{m.symbol:<12}| {m.change_pct:>+6.2f}% | {m.volume_ratio:>7.1f}x | {m.gap_pct:>+5.2f}%"
        )
    return "\n".join(lines)


def build_screen_prompt(
    metrics_list: list[ScannerMetrics],
    max_candidates: int = 5,
) -> str:
    """Build the technical screening prompt from a list of metrics."""
    table = format_metrics_table(metrics_list)
    return SCREEN_PROMPT_TEMPLATE.format(
        max_candidates=max_candidates,
        metrics_table=table,
    )


def build_news_prompt(
    symbols: list[str],
    max_candidates: int = 3,
) -> str:
    """Build a news-aware screening prompt for Perplexity Sonar.

    Perplexity Sonar is web-grounded — it can search the web in real time
    to find breaking news and event-driven catalysts.
    """
    return NEWS_SCREEN_PROMPT_TEMPLATE.format(
        max_candidates=max_candidates,
        symbols=", ".join(symbols),
    )


def build_social_prompt(
    symbols: list[str],
    max_candidates: int = 3,
) -> str:
    """Build a social sentiment screening prompt for Grok.

    Grok is used for social sentiment analysis — it excels at detecting
    retail sentiment shifts and trending discussions about stocks.
    """
    return SOCIAL_SCREEN_PROMPT_TEMPLATE.format(
        max_candidates=max_candidates,
        symbols=", ".join(symbols),
    )


def build_tavily_news_query(symbols: list[str]) -> str:
    """Convert a symbol list into a Tavily search query for Indian equity news.

    Produces a concise query that Tavily's news topic can handle well.
    """
    # Limit query length — Tavily recommends <400 chars
    symbol_str = " OR ".join(symbols[:10])
    return f"NSE India stock market news {symbol_str}"


def parse_tavily_results(
    results: list[dict[str, Any]],
    max_candidates: int = 3,
) -> list[ScannerCandidate]:
    """Convert Tavily search results into ScannerCandidate objects.

    Each Tavily result has: title, url, content, score, published_date.
    We extract stock symbols mentioned in the title/content and build
    candidates from the most relevant results.
    """
    candidates: list[ScannerCandidate] = []
    seen_symbols: set[str] = set()

    for result in results:
        if len(candidates) >= max_candidates:
            break

        title = result.get("title", "")
        content = result.get("content", "")
        score = result.get("score", 0)
        text = f"{title} {content}"

        # Try to extract NSE symbols (uppercase words that look like tickers)
        # Common Indian stock symbols: 2-20 uppercase letters, sometimes with &
        ticker_pattern = r'\b([A-Z][A-Z&]{1,19})\b'
        matches = re.findall(ticker_pattern, text)

        # Filter out common English words that look like tickers
        noise = {
            "THE", "AND", "FOR", "WITH", "FROM", "THIS", "THAT", "WILL",
            "HAS", "HAD", "ARE", "WAS", "NOT", "BUT", "ALL", "NEW", "ITS",
            "CAN", "MAY", "NOW", "HOW", "WHO", "NSE", "BSE", "IPO", "CEO",
            "CFO", "INR", "USD", "RBI", "SEBI", "ETF", "FII", "DII",
        }
        symbols_found = [s for s in matches if s not in noise and len(s) >= 3]

        for sym in symbols_found:
            if sym in seen_symbols:
                continue
            if len(candidates) >= max_candidates:
                break
            seen_symbols.add(sym)
            reason = title[:100] if title else content[:100]
            candidates.append(ScannerCandidate(
                symbol=sym,
                reason=reason,
                urgency="high" if score > 0.7 else "normal",
                metrics={"tavily_score": score},
            ))

    return candidates


def _try_parse_json(text: str) -> Any:
    """Try to parse JSON, recovering from common LLM truncation issues.

    Attempts in order:
    1. Direct parse
    2. Strip trailing commas before ] or }
    3. Close truncated array/objects by appending missing brackets
    """
    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Strip trailing commas (common LLM quirk)
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 3. Truncated response — try closing brackets
    # Find the last complete JSON object in a truncated array
    # e.g. '[{"symbol":"A",...}, {"symbol":"B"' → extract first complete object
    if text.startswith("["):
        # Find all complete objects by looking for }
        depth = 0
        last_complete = -1
        for i, ch in enumerate(text):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    last_complete = i

        if last_complete > 0:
            truncated = text[: last_complete + 1] + "]"
            try:
                return json.loads(truncated)
            except json.JSONDecodeError:
                pass

    return None


def parse_screen_response(response_text: str) -> list[ScannerCandidate]:
    """Parse the LLM JSON response into ScannerCandidate objects.

    Handles common LLM quirks: markdown code fences, trailing commas,
    extra whitespace, and **truncated responses** (cuts off mid-JSON).
    """
    text = response_text.strip()

    # Strip markdown code fence if present
    if text.startswith("```"):
        # Remove first and last lines (```json and ```)
        lines = text.split("\n")
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        )

    text = text.strip()

    data = _try_parse_json(text)
    if data is None:
        logger.warning("Failed to parse scanner LLM response: %s", text[:200])
        return []

    if not isinstance(data, list):
        logger.warning("Scanner LLM response is not a list: %s", type(data))
        return []

    candidates = []
    for item in data:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol", "")
        reason = item.get("reason", "")
        if not symbol:
            continue
        candidates.append(
            ScannerCandidate(
                symbol=symbol.upper(),
                reason=reason[:200],
                urgency=item.get("urgency", "normal"),
                metrics=item.get("metrics", {}),
            )
        )

    return candidates

"""Tests for the scanner screening prompt and response parser."""

import pytest

from skopaq.scanner.models import ScannerMetrics
from skopaq.scanner.screen import (
    build_screen_prompt,
    build_tavily_news_query,
    format_metrics_table,
    parse_screen_response,
    parse_tavily_results,
)


class TestFormatMetricsTable:
    def test_formats_header_and_rows(self):
        metrics = [
            ScannerMetrics(symbol="RELIANCE", ltp=2500.0, change_pct=1.5, volume=100000, volume_ratio=2.3, gap_pct=0.5),
            ScannerMetrics(symbol="TCS", ltp=3400.0, change_pct=-0.8, volume=50000, volume_ratio=0.9, gap_pct=-0.2),
        ]
        table = format_metrics_table(metrics)
        lines = table.split("\n")

        assert "Symbol" in lines[0]
        assert "Change%" in lines[0]
        assert "VolRatio" in lines[0]
        assert "---" in lines[1]
        assert "RELIANCE" in lines[2]
        assert "TCS" in lines[3]

    def test_empty_metrics(self):
        table = format_metrics_table([])
        lines = table.split("\n")
        assert len(lines) == 2  # header + separator only


class TestBuildScreenPrompt:
    def test_includes_max_candidates(self):
        metrics = [ScannerMetrics(symbol="INFY", ltp=1800.0)]
        prompt = build_screen_prompt(metrics, max_candidates=3)
        assert "up to 3" in prompt

    def test_includes_metrics_table(self):
        metrics = [ScannerMetrics(symbol="INFY", ltp=1800.0, change_pct=2.1)]
        prompt = build_screen_prompt(metrics)
        assert "INFY" in prompt
        assert "+2.10%" in prompt

    def test_includes_json_instruction(self):
        prompt = build_screen_prompt([ScannerMetrics(symbol="X")])
        assert "JSON" in prompt


class TestParseScreenResponse:
    def test_parses_valid_json(self):
        response = '[{"symbol": "RELIANCE", "reason": "Strong breakout", "urgency": "high"}]'
        candidates = parse_screen_response(response)
        assert len(candidates) == 1
        assert candidates[0].symbol == "RELIANCE"
        assert candidates[0].reason == "Strong breakout"
        assert candidates[0].urgency == "high"

    def test_parses_multiple_candidates(self):
        response = """[
            {"symbol": "RELIANCE", "reason": "Breakout", "urgency": "high"},
            {"symbol": "TCS", "reason": "Volume surge", "urgency": "normal"}
        ]"""
        candidates = parse_screen_response(response)
        assert len(candidates) == 2
        assert candidates[0].symbol == "RELIANCE"
        assert candidates[1].symbol == "TCS"

    def test_strips_markdown_code_fence(self):
        response = '```json\n[{"symbol": "INFY", "reason": "Gap up"}]\n```'
        candidates = parse_screen_response(response)
        assert len(candidates) == 1
        assert candidates[0].symbol == "INFY"

    def test_uppercases_symbol(self):
        response = '[{"symbol": "reliance", "reason": "test"}]'
        candidates = parse_screen_response(response)
        assert candidates[0].symbol == "RELIANCE"

    def test_truncates_long_reason(self):
        long_reason = "x" * 500
        response = f'[{{"symbol": "TCS", "reason": "{long_reason}"}}]'
        candidates = parse_screen_response(response)
        assert len(candidates[0].reason) <= 200

    def test_defaults_urgency_to_normal(self):
        response = '[{"symbol": "INFY", "reason": "test"}]'
        candidates = parse_screen_response(response)
        assert candidates[0].urgency == "normal"

    def test_empty_array(self):
        assert parse_screen_response("[]") == []

    def test_malformed_json_returns_empty(self):
        assert parse_screen_response("not json at all") == []

    def test_non_list_json_returns_empty(self):
        assert parse_screen_response('{"symbol": "RELIANCE"}') == []

    def test_skips_items_without_symbol(self):
        response = '[{"reason": "no symbol"}, {"symbol": "TCS", "reason": "valid"}]'
        candidates = parse_screen_response(response)
        assert len(candidates) == 1
        assert candidates[0].symbol == "TCS"

    def test_skips_non_dict_items(self):
        response = '["just a string", {"symbol": "TCS", "reason": "valid"}]'
        candidates = parse_screen_response(response)
        assert len(candidates) == 1

    def test_recovers_truncated_json(self):
        """LLM response cut off mid-JSON — recover completed objects."""
        # Simulates: Gemini ran out of tokens mid-response
        response = (
            '[{"symbol": "RELIANCE", "reason": "Strong bearish signal", "urgency": "high"}, '
            '{"symbol": "TCS", "reason": "Bullish momen'  # <-- truncated here
        )
        candidates = parse_screen_response(response)
        # Should recover the first complete object
        assert len(candidates) == 1
        assert candidates[0].symbol == "RELIANCE"

    def test_recovers_trailing_comma_json(self):
        """LLM produces trailing comma before closing bracket."""
        response = '[{"symbol": "INFY", "reason": "Gap up", "urgency": "high"},]'
        candidates = parse_screen_response(response)
        assert len(candidates) == 1
        assert candidates[0].symbol == "INFY"


class TestBuildTavilyNewsQuery:
    def test_basic_query(self):
        query = build_tavily_news_query(["RELIANCE", "TCS"])
        assert "NSE India stock market news" in query
        assert "RELIANCE" in query
        assert "TCS" in query

    def test_symbols_joined_with_or(self):
        query = build_tavily_news_query(["RELIANCE", "TCS", "INFY"])
        assert "RELIANCE OR TCS OR INFY" in query

    def test_caps_at_10_symbols(self):
        symbols = [f"SYM{i}" for i in range(25)]
        query = build_tavily_news_query(symbols)
        # Only first 10 symbols should appear
        assert "SYM9" in query
        assert "SYM10" not in query

    def test_empty_symbols(self):
        query = build_tavily_news_query([])
        assert "NSE India stock market news" in query

    def test_single_symbol(self):
        query = build_tavily_news_query(["RELIANCE"])
        assert query == "NSE India stock market news RELIANCE"


class TestParseTavilyResults:
    def test_empty_results(self):
        assert parse_tavily_results([]) == []

    def test_extracts_ticker_from_title(self):
        results = [
            {"title": "RELIANCE shares surge 5% on Q4 results", "content": "Strong earnings.", "score": 0.9}
        ]
        candidates = parse_tavily_results(results)
        assert len(candidates) == 1
        assert candidates[0].symbol == "RELIANCE"

    def test_filters_noise_words(self):
        results = [
            {"title": "THE NEW CEO FOR THIS IPO", "content": "No real ticker here.", "score": 0.5}
        ]
        candidates = parse_tavily_results(results)
        assert len(candidates) == 0

    def test_max_candidates_cap(self):
        tickers = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
                    "SBIN", "BAJAJ", "MARUTI", "WIPRO", "SUNPHARMA"]
        results = [
            {"title": f"{t} stock rallies", "content": "", "score": 0.8}
            for t in tickers
        ]
        candidates = parse_tavily_results(results, max_candidates=3)
        assert len(candidates) == 3

    def test_high_urgency_threshold(self):
        results = [
            {"title": "RELIANCE breaks out", "content": "", "score": 0.9},
        ]
        candidates = parse_tavily_results(results)
        assert candidates[0].urgency == "high"

    def test_normal_urgency_below_threshold(self):
        results = [
            {"title": "RELIANCE steady gains", "content": "", "score": 0.5},
        ]
        candidates = parse_tavily_results(results)
        assert candidates[0].urgency == "normal"

    def test_deduplicates_symbols(self):
        results = [
            {"title": "RELIANCE Q4 results", "content": "RELIANCE beats estimates", "score": 0.8},
        ]
        candidates = parse_tavily_results(results)
        # Should not produce duplicate RELIANCE entries
        reliance_count = sum(1 for c in candidates if c.symbol == "RELIANCE")
        assert reliance_count == 1

    def test_reason_from_title(self):
        results = [
            {"title": "INFY announces buyback", "content": "Details inside.", "score": 0.6}
        ]
        candidates = parse_tavily_results(results)
        assert candidates[0].reason == "INFY announces buyback"

    def test_result_missing_fields(self):
        results = [{}]
        candidates = parse_tavily_results(results)
        assert candidates == []

    def test_tavily_score_in_metrics(self):
        results = [
            {"title": "TCS wins deal", "content": "", "score": 0.85}
        ]
        candidates = parse_tavily_results(results)
        assert candidates[0].metrics["tavily_score"] == 0.85

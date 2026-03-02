"""Tests for the scanner screening prompt and response parser."""

import pytest

from skopaq.scanner.models import ScannerMetrics
from skopaq.scanner.screen import (
    build_screen_prompt,
    format_metrics_table,
    parse_screen_response,
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

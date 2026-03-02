"""Integration tests — real LLM connectivity.

Run with: python3 -m pytest tests/integration/ -v -m integration
Requires: .env with real API keys
"""

import os
import pytest

# Load .env before anything else — override=True needed because
# Claude Code's shell sets ANTHROPIC_API_KEY="" which masks the .env value
from dotenv import load_dotenv
load_dotenv(override=True)


pytestmark = pytest.mark.integration


def _extract_text(content) -> str:
    """Extract text from LangChain response content.

    Gemini 3 returns content as a list of dicts: [{"type": "text", "text": "..."}]
    while other models return a plain string.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return " ".join(parts).strip()
    return str(content).strip()


# ── 1. Environment Bridge ──────────────────────────────────────────


class TestEnvBridge:
    """Verify that real keys from .env get bridged correctly."""

    def test_google_key_present(self):
        key = os.environ.get("GOOGLE_API_KEY", "")
        assert len(key) > 10, f"GOOGLE_API_KEY not set or too short ({len(key)} chars)"

    def test_anthropic_key_present(self):
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        assert len(key) > 10, f"ANTHROPIC_API_KEY not set or too short ({len(key)} chars)"

    def test_bridge_populates_from_skopaq_prefix(self):
        """bridge_env_vars should read SKOPAQ_ prefixed keys from config."""
        from skopaq.llm.env_bridge import bridge_env_vars

        # Clear standard vars, let bridge re-populate from SKOPAQ_ variants
        saved = {}
        for var in ["GOOGLE_API_KEY", "ANTHROPIC_API_KEY"]:
            saved[var] = os.environ.pop(var, None)

        try:
            bridged = bridge_env_vars()
            # At least google should be bridged from SKOPAQ_GOOGLE_API_KEY
            assert "GOOGLE_API_KEY" in bridged or os.environ.get("GOOGLE_API_KEY"), \
                "Bridge did not populate GOOGLE_API_KEY"
        finally:
            # Restore
            for var, val in saved.items():
                if val:
                    os.environ[var] = val


# ── 2. Gemini Flash ────────────────────────────────────────────────


class TestGeminiConnectivity:
    """Test actual Gemini API call."""

    def test_gemini_flash_responds(self):
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model="gemini-3-flash-preview",
            temperature=0,
        )
        response = llm.invoke("Reply with exactly one word: hello")
        text = _extract_text(response.content).lower()
        assert len(text) > 0, "Gemini returned empty response"
        print(f"  Gemini 3 Flash response: {text!r}")


# ── 3. Anthropic Claude ───────────────────────────────────────────


class TestClaudeConnectivity:
    """Test actual Claude API call."""

    def test_claude_opus_responds(self):
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            pytest.skip("ANTHROPIC_API_KEY not set")

        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(
            model="claude-opus-4-6",
            temperature=0,
            max_tokens=50,
        )
        response = llm.invoke("Reply with exactly one word: hello")
        text = response.content.strip().lower()
        assert len(text) > 0, "Claude returned empty response"
        print(f"  Claude Opus 4.6 response: {text!r}")


# ── 4. Model Tier Builder ─────────────────────────────────────────


class TestModelTierBuilder:
    """Test that build_llm_map creates usable LLM instances from real keys."""

    def test_build_llm_map_succeeds(self):
        from skopaq.llm.model_tier import build_llm_map

        llm_map = build_llm_map()
        assert "_default" in llm_map, "No _default key in llm_map"
        assert len(llm_map) > 1, f"Only {len(llm_map)} entries — expected more roles"
        print(f"  LLM map has {len(llm_map)} entries: {list(llm_map.keys())}")

    def test_default_model_responds(self):
        from skopaq.llm.model_tier import build_llm_map

        llm_map = build_llm_map()
        default_llm = llm_map["_default"]
        response = default_llm.invoke("Reply with exactly one word: test")
        text = _extract_text(response.content)
        assert len(text) > 0, "Default LLM returned empty"
        print(f"  Default LLM response: {text!r}")

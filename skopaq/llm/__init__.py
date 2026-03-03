"""LLM utilities — environment bridging, multi-model tiering, and caching."""

from skopaq.llm.cache import init_langcache
from skopaq.llm.env_bridge import bridge_env_vars
from skopaq.llm.model_tier import build_llm_map


def extract_text(content) -> str:
    """Extract plain text from a LangChain response's ``.content`` attribute.

    Gemini 3 models return content as a list of dicts::

        [{"type": "text", "text": "Hello", "extras": {...}}]

    while other models (Claude, GPT, Grok) return a plain string.
    This helper normalizes both formats to a plain string.
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


__all__ = ["bridge_env_vars", "build_llm_map", "extract_text", "init_langcache"]

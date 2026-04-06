"""Interactive AI trading chatbot — Claude Code-style REPL + OpenClaw bridge."""

__all__ = ["ChatSession"]


def __getattr__(name: str):
    if name == "ChatSession":
        from skopaq.chat.session import ChatSession

        return ChatSession
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

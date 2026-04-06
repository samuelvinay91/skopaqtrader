"""Interactive REPL loop — Claude Code-style trading chatbot.

Uses ``prompt_toolkit`` for input (history, async, keyboard handling) and
Rich for output (streaming tokens, tool panels, Markdown).

**Human-in-the-Loop** — The agent uses ``interrupt_before=["tools"]``
so every tool call pauses for inspection.  Non-gated tools (quotes,
portfolio, etc.) are auto-approved; gated tools (``trade_stock``) require
explicit user confirmation before execution.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout

from skopaq.chat.display import (
    StreamingDisplay,
    display_chat_error,
    display_chat_goodbye,
    display_chat_info,
    display_chat_welcome,
    display_help,
    display_history_summary,
    display_mode_change,
    display_tool_end,
    display_tool_start,
)
from skopaq.chat.session import ChatSession
from skopaq.cli.theme import BRAND_DIM, WARNING, console

logger = logging.getLogger(__name__)

# Prompt style
_PROMPT = "\n> "


async def run_repl(session: ChatSession) -> None:
    """Run the interactive chat REPL.

    Args:
        session: An initialised ChatSession with config loaded.
    """
    from skopaq import __version__

    display_chat_welcome(
        mode=session.config.trading_mode,
        asset_class=session.config.asset_class,
        version=__version__,
    )

    prompt_session: PromptSession = PromptSession(
        history=InMemoryHistory(),
    )

    consecutive_interrupts = 0

    while True:
        try:
            with patch_stdout():
                user_input = await prompt_session.prompt_async(_PROMPT)
            consecutive_interrupts = 0
        except KeyboardInterrupt:
            consecutive_interrupts += 1
            if consecutive_interrupts >= 2:
                display_chat_goodbye()
                return
            console.print("\n  Press Ctrl+C again to exit, or keep chatting.", style=BRAND_DIM)
            continue
        except EOFError:
            display_chat_goodbye()
            return

        text = user_input.strip()
        if not text:
            continue

        # Handle slash commands
        if text.startswith("/"):
            should_exit = await _handle_slash_command(text, session)
            if should_exit:
                return
            continue

        # Natural language → agent
        session.add_user_message(text)
        try:
            await _run_agent_with_hitl(session)
        except asyncio.CancelledError:
            console.print("\n  (cancelled)", style="dim")
        except Exception as exc:
            logger.exception("Agent response failed")
            display_chat_error(str(exc))


async def _handle_slash_command(text: str, session: ChatSession) -> bool:
    """Process a slash command. Returns True if the REPL should exit."""
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/exit", "/quit"):
        display_chat_goodbye()
        return True

    if cmd == "/help":
        display_help()
        return False

    if cmd == "/clear":
        session.clear()
        display_chat_info("Conversation cleared.")
        return False

    if cmd == "/history":
        display_history_summary(session.messages)
        return False

    if cmd in ("/mode",):
        if not arg:
            mode = session.config.trading_mode
            display_chat_info(f"Current mode: {mode.upper()}")
        elif arg.lower() in ("paper", "live"):
            new_mode = arg.lower()
            if new_mode == "live":
                console.print(
                    "\n  [bold red]WARNING:[/bold red] Live mode uses real money!",
                )
                try:
                    confirm = await _prompt_confirm("  Switch to LIVE mode?")
                    if not confirm:
                        display_chat_info("Mode not changed.")
                        return False
                except (KeyboardInterrupt, EOFError):
                    display_chat_info("Mode not changed.")
                    return False
            session.config.trading_mode = new_mode
            # Rebuild infrastructure with new mode
            session.infra = None
            session.agent = None
            display_mode_change(new_mode)
        else:
            display_chat_info("Usage: /mode [paper|live]")
        return False

    # Direct tool shortcuts (bypass LLM for speed)
    if cmd == "/scan":
        max_candidates = int(arg) if arg.isdigit() else 5
        await _run_slash_tool(session, "scan_market", max_candidates=max_candidates)
        return False

    if cmd in ("/portfolio", "/positions"):
        await _run_slash_tool(session, "get_portfolio")
        return False

    if cmd == "/orders":
        await _run_slash_tool(session, "get_orders")
        return False

    if cmd == "/status":
        await _run_slash_tool(session, "check_status")
        return False

    if cmd == "/quote":
        if not arg:
            display_chat_info("Usage: /quote SYMBOL (e.g., /quote RELIANCE)")
            return False
        await _run_slash_tool(session, "get_quote", symbol=arg.upper())
        return False

    display_chat_info(f"Unknown command: {cmd}. Type /help for available commands.")
    return False


async def _run_slash_tool(
    session: ChatSession,
    tool_name: str,
    **kwargs: Any,
) -> None:
    """Run a tool directly (no LLM) for slash command shortcuts."""
    from skopaq.chat.tools import get_all_tools, init_tools

    infra = session.ensure_infra()
    init_tools(infra)

    # Find the tool function
    tools = get_all_tools()
    tool_fn = None
    for t in tools:
        if t.name == tool_name:
            tool_fn = t
            break

    if tool_fn is None:
        display_chat_error(f"Tool not found: {tool_name}")
        return

    display_tool_start(tool_name, kwargs)

    try:
        result = await tool_fn.ainvoke(kwargs)
        display_tool_end(tool_name, result)
    except Exception as exc:
        logger.exception("Slash tool %s failed", tool_name)
        display_chat_error(f"{tool_name} failed: {exc}")


# ── Human-in-the-Loop Agent Runner ──────────────────────────────────────────


async def _run_agent_with_hitl(session: ChatSession) -> None:
    """Run the agent with interrupt-based human-in-the-loop.

    Flow:
    1. Invoke agent with conversation history
    2. Agent streams its thinking, then stops at ``interrupt_before=["tools"]``
    3. Inspect pending tool calls in the checkpoint state
    4. If tool is gated (``trade_stock``), prompt user for confirmation
    5. If approved (or non-gated tool), resume agent → tool executes → loop
    6. If denied, inject cancellation and let agent respond

    The loop continues until the agent finishes (no more tool calls).
    """
    from skopaq.chat.agent import GATED_TOOLS

    agent = session.ensure_agent()
    config = session.thread_config

    # First invocation — send user message to agent
    ai_text = await _stream_until_interrupt(
        agent, {"messages": session.get_history()}, config, session,
    )

    # The agent may have interrupted before a tool call.
    # Loop: inspect pending tools → approve/deny → resume → repeat
    while True:
        # Check the checkpoint state for pending tool calls
        state = agent.get_state(config)
        pending_tasks = state.tasks if hasattr(state, "tasks") else ()

        # If there are no pending tasks, the agent has finished
        if not pending_tasks:
            break

        # Check what tool the agent wants to call by inspecting the
        # last AI message's tool_calls
        last_msg = state.values.get("messages", [])[-1] if state.values.get("messages") else None
        tool_calls = []
        if last_msg and hasattr(last_msg, "tool_calls"):
            tool_calls = last_msg.tool_calls or []

        if not tool_calls:
            # No tool calls pending — resume normally
            ai_text = await _stream_until_interrupt(agent, None, config, session)
            continue

        # Check if any pending tool is gated
        needs_approval = False
        for tc in tool_calls:
            tool_name = tc.get("name", "")
            tool_args = tc.get("args", {})

            if tool_name in GATED_TOOLS:
                needs_approval = True
                # Show what's about to happen
                console.print()
                console.print(
                    f"  [bold yellow]CONFIRM:[/bold yellow] Agent wants to "
                    f"execute [bold]{tool_name}[/bold]",
                )
                for k, v in tool_args.items():
                    if v:
                        console.print(f"    {k}: {v}", style="dim")

                try:
                    approved = await _prompt_confirm(
                        "  Execute this trade?"
                    )
                except (KeyboardInterrupt, EOFError):
                    approved = False

                if not approved:
                    # Cancel: update state to remove the pending tool call
                    # by sending a None resume, which will skip the tools node
                    console.print("  Trade cancelled by user.", style=WARNING)
                    # Add a tool response that says "cancelled" so the agent
                    # can acknowledge it gracefully
                    from langchain_core.messages import ToolMessage

                    cancel_messages = []
                    for tc_item in tool_calls:
                        cancel_messages.append(
                            ToolMessage(
                                content="Trade cancelled by user.",
                                tool_call_id=tc_item["id"],
                            )
                        )
                    agent.update_state(
                        config,
                        {"messages": cancel_messages},
                    )
                    # Resume so agent can acknowledge the cancellation
                    ai_text = await _stream_until_interrupt(
                        agent, None, config, session,
                    )
                    continue
            else:
                display_tool_start(tool_name, tool_args)

        if needs_approval and not approved:
            continue

        # Auto-approve non-gated tools, or user approved gated tool
        # Resume the agent from the checkpoint (it continues with tool execution)
        ai_text = await _stream_until_interrupt(agent, None, config, session)

    # Save final AI response to session history
    if ai_text and ai_text.strip():
        session.add_ai_message(ai_text)


async def _stream_until_interrupt(
    agent,
    input_data: dict | None,
    config: dict,
    session: ChatSession,
) -> str:
    """Stream agent events until it finishes or hits an interrupt.

    Args:
        agent: The compiled LangGraph agent.
        input_data: Input dict for first call, or None for resume.
        config: Thread config with thread_id.
        session: Current chat session.

    Returns:
        The accumulated AI text from this invocation segment.
    """
    streamer = StreamingDisplay()
    current_tool: str | None = None
    ai_text_parts: list[str] = []
    seen_model_runs: set[str] = set()
    streaming_run_id: str | None = None

    try:
        async for event in agent.astream_events(
            input_data,
            config=config,
            version="v2",
        ):
            kind = event.get("event", "")

            # ── LLM token streaming ──────────────────────────────────
            if kind == "on_chat_model_stream":
                run_id = event.get("run_id", "")

                if run_id not in seen_model_runs:
                    seen_model_runs.add(run_id)
                    if current_tool is None:
                        streaming_run_id = run_id

                if run_id != streaming_run_id:
                    continue

                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    content = chunk.content
                    if isinstance(content, str):
                        token = content
                    elif isinstance(content, list) and content:
                        token = (
                            content[0].get("text", "")
                            if isinstance(content[0], dict)
                            else str(content[0])
                        )
                    else:
                        continue

                    if not token:
                        continue

                    if current_tool is None:
                        if not streamer._started:
                            streamer.start()
                        streamer.add_token(token)
                        ai_text_parts.append(token)

            # ── Tool call start ──────────────────────────────────────
            elif kind == "on_tool_start":
                if streamer._started:
                    streamer.finish()

                tool_name = event.get("name", "unknown")
                tool_input = event.get("data", {}).get("input", {})
                current_tool = tool_name
                streaming_run_id = None
                display_tool_start(tool_name, tool_input)

            # ── Tool call end ────────────────────────────────────────
            elif kind == "on_tool_end":
                tool_name = event.get("name", "unknown")
                output = event.get("data", {}).get("output", "")
                if hasattr(output, "content"):
                    output = output.content
                display_tool_end(tool_name, str(output))
                current_tool = None

        # Finish any remaining stream
        if streamer._started:
            streamer.finish()

    except asyncio.CancelledError:
        streamer.cancel()
        raise
    except KeyboardInterrupt:
        streamer.cancel()
        console.print("\n  (interrupted)", style="dim")
    except Exception:
        streamer.cancel()
        raise

    return "".join(ai_text_parts)


async def _prompt_confirm(message: str) -> bool:
    """Prompt for yes/no confirmation."""
    prompt_session: PromptSession = PromptSession()
    with patch_stdout():
        answer = await prompt_session.prompt_async(f"{message} [y/N] ")
    return answer.strip().lower() in ("y", "yes")

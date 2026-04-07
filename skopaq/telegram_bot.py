"""Telegram bot for SkopaqTrader — trade alerts, portfolio, and commands.

Run standalone::

    python -m skopaq.telegram_bot

Commands:
    /start          — Welcome message
    /quote SYMBOL   — Real-time stock quote
    /portfolio      — Positions, holdings, funds
    /status         — System health check
    /analyze SYMBOL — Quick Claude-style analysis (using data tools)
    /pnl            — Current P&L on open positions
    /help           — List commands
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)


# ── Lazy infrastructure ──────────────────────────────────────────────────────

_infra_ready = False


def _ensure_infra():
    """Bridge env vars on first use."""
    global _infra_ready
    if not _infra_ready:
        from skopaq.config import SkopaqConfig
        from skopaq.llm import bridge_env_vars

        config = SkopaqConfig()
        bridge_env_vars(config)
        _infra_ready = True


# ── Command Handlers ─────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message."""
    await update.message.reply_text(
        "Welcome to *SkopaqTrader* \\! Your AI trading assistant\\.\n\n"
        "Commands:\n"
        "/quote SYMBOL \\- Live stock quote\n"
        "/portfolio \\- Positions \\& P\\&L\n"
        "/status \\- System health\n"
        "/pnl \\- Open position P\\&L\n"
        "/help \\- All commands\n\n"
        "Or just type a stock symbol to get a quick quote\\.",
        parse_mode="MarkdownV2",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all commands."""
    await update.message.reply_text(
        "/quote SYMBOL — Real-time quote (LTP, OHLC, volume)\n"
        "/portfolio — Positions, holdings, funds\n"
        "/status — System health, mode, token\n"
        "/pnl — P&L on open positions\n"
        "/analyze SYMBOL — Quick technical analysis\n"
        "/help — This message"
    )


async def cmd_quote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Get real-time stock quote."""
    if not context.args:
        await update.message.reply_text("Usage: /quote RELIANCE")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(f"Fetching {symbol}...")

    try:
        _ensure_infra()
        from skopaq.mcp_server import get_quote

        result = json.loads(await get_quote(symbol))
        if "error" in result:
            await update.message.reply_text(f"Error: {result['error']}")
            return

        msg = (
            f"*{result['symbol']}* \\({result['exchange']}\\)\n\n"
            f"LTP: Rs {result['ltp']:,.2f} \\({result['change_pct']:+.2f}%\\)\n"
            f"Open: {result['open']:,.2f} \\| High: {result['high']:,.2f}\n"
            f"Low: {result['low']:,.2f} \\| Close: {result['close']:,.2f}\n"
            f"Volume: {result['volume']:,}"
        ).replace(".", "\\.").replace("-", "\\-").replace("+", "\\+").replace("(", "\\(").replace(")", "\\)")
        # Simpler approach — just use plain text
        plain = (
            f"{result['symbol']} ({result['exchange']})\n\n"
            f"LTP: Rs {result['ltp']:,.2f} ({result['change_pct']:+.2f}%)\n"
            f"Open: {result['open']:,.2f} | High: {result['high']:,.2f}\n"
            f"Low: {result['low']:,.2f} | Close: {result['close']:,.2f}\n"
            f"Volume: {result['volume']:,}"
        )
        await update.message.reply_text(plain)

    except Exception as exc:
        logger.exception("Quote failed")
        await update.message.reply_text(f"Error: {exc}")


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show portfolio — positions, holdings, funds."""
    await update.message.reply_text("Fetching portfolio...")

    try:
        _ensure_infra()
        from skopaq.mcp_server import get_positions, get_holdings, get_funds

        positions = json.loads(await get_positions())
        funds = json.loads(await get_funds())

        lines = [
            f"Cash: Rs {funds['available_cash']:,.2f}",
            f"Margin Used: Rs {funds['used_margin']:,.2f}",
            "",
        ]

        if positions:
            lines.append(f"Positions ({len(positions)}):")
            for p in positions:
                pnl_str = f"{p['pnl']:+,.2f}" if p.get('pnl') else "0"
                lines.append(
                    f"  {p['symbol']} | Qty: {p['quantity']} | "
                    f"Avg: {p['avg_price']:,.2f} | PnL: {pnl_str}"
                )
        else:
            lines.append("No open positions.")

        await update.message.reply_text("\n".join(lines))

    except Exception as exc:
        logger.exception("Portfolio failed")
        await update.message.reply_text(f"Error: {exc}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """System health check."""
    try:
        _ensure_infra()
        from skopaq.mcp_server import system_status

        result = json.loads(await system_status())
        msg = (
            f"SkopaqTrader v{result['version']}\n"
            f"Mode: {result['mode'].upper()}\n"
            f"Asset: {result['asset_class']}\n"
            f"Token: {'Valid' if result['token_valid'] else 'EXPIRED'}\n"
            f"LLMs: {', '.join(result['llms'])}\n"
            f"Capital: Rs {result['paper_capital']:,.0f}"
        )
        await update.message.reply_text(msg)

    except Exception as exc:
        await update.message.reply_text(f"Error: {exc}")


async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show P&L on open positions with live quotes."""
    try:
        _ensure_infra()
        from skopaq.config import SkopaqConfig
        from skopaq.broker.client import INDstocksClient
        from skopaq.broker.token_manager import TokenManager
        from skopaq.broker.scrip_resolver import resolve_scrip_code

        config = SkopaqConfig()
        config.trading_mode = "live"
        token_mgr = TokenManager()

        async with INDstocksClient(config, token_mgr) as client:
            positions = await client.get_positions()
            if not positions:
                await update.message.reply_text("No open positions.")
                return

            lines = ["Open Positions P&L:\n"]
            total_pnl = 0.0
            for p in positions:
                sym = p.symbol if hasattr(p, 'symbol') else p.get('name', '?')
                qty = float(p.quantity if hasattr(p, 'quantity') else p.get('net_qty', 0))
                avg = float(p.average_price if hasattr(p, 'average_price') else p.get('avg_price', 0))

                try:
                    scrip = await resolve_scrip_code(client, sym)
                    q = await client.get_quote(scrip, symbol=sym)
                    ltp = q.ltp
                except Exception:
                    ltp = avg  # fallback

                pnl = (ltp - avg) * qty
                total_pnl += pnl
                pnl_pct = ((ltp - avg) / avg * 100) if avg else 0
                emoji = "+" if pnl >= 0 else ""
                lines.append(
                    f"{sym}: {int(qty)} @ {avg:.2f} -> {ltp:.2f}\n"
                    f"  P&L: {emoji}{pnl:.2f} ({emoji}{pnl_pct:.2f}%)"
                )

            lines.append(f"\nTotal P&L: Rs {total_pnl:+,.2f}")
            await update.message.reply_text("\n".join(lines))

    except Exception as exc:
        logger.exception("PnL check failed")
        await update.message.reply_text(f"Error: {exc}")


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Quick analysis using MCP data tools."""
    if not context.args:
        await update.message.reply_text("Usage: /analyze RELIANCE")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(f"Analyzing {symbol}... (10-20 sec)")

    try:
        _ensure_infra()
        from skopaq.mcp_server import gather_market_data

        data = json.loads(await gather_market_data(symbol))
        indicators = data.get("indicators", {})

        # Extract key values
        rsi_text = indicators.get("rsi", "")
        macd_text = indicators.get("macd", "")
        atr_text = indicators.get("atr", "")

        # Parse latest values
        def extract_latest(text):
            for line in text.split("\n"):
                if "N/A" not in line and ":" in line and "##" not in line and "values" not in line.lower():
                    parts = line.split(":")
                    if len(parts) >= 2:
                        try:
                            return float(parts[-1].strip())
                        except ValueError:
                            continue
            return None

        rsi = extract_latest(rsi_text)
        macd = extract_latest(macd_text)
        atr = extract_latest(atr_text)

        # Quick signal
        signal = "NEUTRAL"
        if rsi and rsi < 35:
            signal = "OVERSOLD (potential BUY)"
        elif rsi and rsi > 65:
            signal = "OVERBOUGHT (potential SELL)"
        elif rsi and rsi < 45 and macd and macd < 0:
            signal = "BEARISH"
        elif rsi and rsi > 55 and macd and macd > 0:
            signal = "BULLISH"

        msg = (
            f"Quick Analysis: {symbol}\n\n"
            f"RSI: {rsi:.1f}\n" if rsi else f"RSI: N/A\n"
        )
        msg += f"MACD: {macd:.2f}\n" if macd else "MACD: N/A\n"
        msg += f"ATR: {atr:.2f}\n" if atr else "ATR: N/A\n"
        msg += f"\nSignal: {signal}"
        msg += "\n\nUse Claude Code /analyze for full 15-agent pipeline."

        await update.message.reply_text(msg)

    except Exception as exc:
        logger.exception("Analyze failed")
        await update.message.reply_text(f"Error: {exc}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle natural language — route through the AI chat brain.

    This gives the Telegram bot the same intelligence as Claude Code.
    The ReAct agent can call MCP tools (quotes, portfolio, analysis)
    based on the user's natural language input.
    """
    text = update.message.text.strip()
    chat_id = update.message.chat.id

    # Show typing indicator
    await update.message.chat.send_action("typing")

    try:
        _ensure_infra()
        from skopaq.chat.session import ChatSession
        from skopaq.config import SkopaqConfig

        # Get or create session for this chat
        session = _get_chat_session(chat_id)
        session.add_user_message(text)

        agent = session.ensure_agent()
        config = session.thread_config

        # Run agent with auto-resume for interrupts
        result = await agent.ainvoke(
            {"messages": session.get_history()},
            config=config,
        )

        # Auto-resume interrupted tool calls
        max_resumes = 10
        for _ in range(max_resumes):
            state = agent.get_state(config)
            if not state.next:
                break
            await update.message.chat.send_action("typing")
            result = await agent.ainvoke(None, config=config)

        # Extract AI response
        messages = result.get("messages", [])
        ai_text = ""
        tool_names = []

        for msg in reversed(messages):
            if hasattr(msg, "type"):
                if msg.type == "ai" and msg.content and not ai_text:
                    ai_text = msg.content if isinstance(msg.content, str) else str(msg.content)
                elif msg.type == "tool":
                    tool_names.append(getattr(msg, "name", "tool"))

        if ai_text:
            session.add_ai_message(ai_text)
            # Telegram has a 4096 char limit
            if len(ai_text) > 4000:
                for i in range(0, len(ai_text), 4000):
                    await update.message.reply_text(ai_text[i:i + 4000])
            else:
                await update.message.reply_text(ai_text)
        else:
            await update.message.reply_text("I processed your request but have no text response.")

    except Exception as exc:
        logger.exception("Chat brain failed")
        await update.message.reply_text(f"Error: {exc}")


# ── Session Management ───────────────────────────────────────────────────────

_telegram_sessions: dict[int, "ChatSession"] = {}


def _get_chat_session(chat_id: int):
    """Get or create a ChatSession for a Telegram chat."""
    if chat_id in _telegram_sessions:
        return _telegram_sessions[chat_id]

    from skopaq.chat.session import ChatSession
    from skopaq.config import SkopaqConfig

    config = SkopaqConfig()
    session = ChatSession(config)
    _telegram_sessions[chat_id] = session
    return session


# ── Alert System ─────────────────────────────────────────────────────────────


async def send_alert(app: Application, chat_id: int, message: str) -> None:
    """Send a trade alert to a specific chat."""
    await app.bot.send_message(chat_id=chat_id, text=message)


# ── Entry Point ──────────────────────────────────────────────────────────────


def main() -> None:
    """Start the Telegram bot."""
    token = os.environ.get("SKOPAQ_TELEGRAM_BOT_TOKEN", "")
    if not token:
        from skopaq.config import SkopaqConfig

        config = SkopaqConfig()
        token = getattr(config, "telegram_bot_token", "")
        if hasattr(token, "get_secret_value"):
            token = token.get_secret_value()

    if not token:
        print("Error: SKOPAQ_TELEGRAM_BOT_TOKEN not set")
        return

    print(f"Starting SkopaqTrader Telegram bot...")

    app = Application.builder().token(token).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("quote", cmd_quote))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pnl", cmd_pnl))
    app.add_handler(CommandHandler("analyze", cmd_analyze))

    # Plain text → quick quote
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Bot ready. Polling for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

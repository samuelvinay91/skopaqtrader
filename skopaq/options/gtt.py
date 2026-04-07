"""GTT (Good Till Triggered) order management via Kite Connect.

GTT orders sit on Zerodha's server and execute automatically when the
trigger price is hit. No monitoring needed — the broker watches 24/7.

Two types:
    - **Single**: One trigger (e.g., buy at support, or stop-loss)
    - **OCO** (One-Cancels-Other): Two triggers — target + stop-loss.
      Whichever hits first executes, the other is cancelled.

This is the safest automation for swing trading:
    1. AI identifies entry at support → place GTT BUY
    2. Once filled, AI places GTT OCO SELL (target + stop-loss)
    3. Zero monitoring. Telegram alert when triggered.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class GTTOrder:
    """A GTT order recommendation."""

    symbol: str
    exchange: str
    trigger_type: str  # "single" or "two-leg" (OCO)
    transaction_type: str  # "BUY" or "SELL"

    # Trigger prices
    trigger_price: float  # For single-trigger
    target_price: float = 0.0  # For OCO (upper trigger)
    stop_loss_price: float = 0.0  # For OCO (lower trigger)

    # Order details
    quantity: int = 1
    limit_price: float = 0.0  # Limit price for execution
    last_price: float = 0.0  # Current price at placement time

    # Metadata
    reasoning: str = ""
    gtt_id: int = 0  # Set after placement


async def place_gtt_buy(
    kite_client,
    symbol: str,
    buy_trigger: float,
    limit_price: float,
    quantity: int,
    exchange: str = "NSE",
) -> dict:
    """Place a GTT BUY order — triggers when price drops to support.

    Args:
        kite_client: Authenticated KiteClient.
        symbol: Trading symbol (e.g., RELIANCE).
        buy_trigger: Price at which to trigger the buy.
        limit_price: Limit price for the buy order.
        quantity: Number of shares.
        exchange: NSE or BSE.

    Returns:
        GTT order response with trigger_id.
    """
    import asyncio

    # Get current price
    quote = await kite_client.get_quote(f"{exchange}:{symbol}", symbol=symbol)

    result = await asyncio.to_thread(
        kite_client._kite.place_gtt,
        trigger_type=kite_client._kite.GTT_TYPE_SINGLE,
        tradingsymbol=symbol,
        exchange=exchange,
        trigger_values=[buy_trigger],
        last_price=quote.ltp,
        orders=[{
            "transaction_type": "BUY",
            "quantity": quantity,
            "price": limit_price,
            "order_type": "LIMIT",
            "product": "CNC",
        }],
    )

    logger.info("GTT BUY placed: %s trigger=%s qty=%s id=%s", symbol, buy_trigger, quantity, result)

    # Auto-notify via Telegram
    from skopaq.notifications import notify_gtt_event

    await notify_gtt_event(
        "PLACED", symbol, buy_trigger,
        trigger_id=result.get("trigger_id", 0), quantity=quantity,
    )

    return result


async def place_gtt_oco_sell(
    kite_client,
    symbol: str,
    target_price: float,
    stop_loss_price: float,
    quantity: int,
    exchange: str = "NSE",
) -> dict:
    """Place a GTT OCO SELL order — target + stop-loss in one order.

    Whichever trigger hits first executes. The other is auto-cancelled.

    Args:
        kite_client: Authenticated KiteClient.
        symbol: Trading symbol.
        target_price: Upper trigger — sell at profit.
        stop_loss_price: Lower trigger — sell to cut loss.
        quantity: Number of shares.
        exchange: NSE or BSE.

    Returns:
        GTT order response with trigger_id.
    """
    import asyncio

    quote = await kite_client.get_quote(f"{exchange}:{symbol}", symbol=symbol)

    result = await asyncio.to_thread(
        kite_client._kite.place_gtt,
        trigger_type=kite_client._kite.GTT_TYPE_OCO,
        tradingsymbol=symbol,
        exchange=exchange,
        trigger_values=[stop_loss_price, target_price],
        last_price=quote.ltp,
        orders=[
            {  # Stop-loss leg
                "transaction_type": "SELL",
                "quantity": quantity,
                "price": stop_loss_price,
                "order_type": "LIMIT",
                "product": "CNC",
            },
            {  # Target leg
                "transaction_type": "SELL",
                "quantity": quantity,
                "price": target_price,
                "order_type": "LIMIT",
                "product": "CNC",
            },
        ],
    )

    logger.info(
        "GTT OCO SELL placed: %s target=%s stop=%s qty=%s id=%s",
        symbol, target_price, stop_loss_price, quantity, result,
    )

    # Auto-notify via Telegram
    from skopaq.notifications import notify_gtt_event

    await notify_gtt_event(
        "PLACED", symbol, stop_loss_price,
        target_price=target_price, stop_loss_price=stop_loss_price,
        trigger_id=result.get("trigger_id", 0), quantity=quantity,
    )

    return result


async def list_gtts(kite_client) -> list[dict]:
    """List all active GTT orders."""
    import asyncio

    gtts = await asyncio.to_thread(kite_client._kite.get_gtts)
    return gtts or []


async def cancel_gtt(kite_client, trigger_id: int) -> dict:
    """Cancel a GTT order by trigger ID."""
    import asyncio

    result = await asyncio.to_thread(kite_client._kite.delete_gtt, trigger_id)
    logger.info("GTT cancelled: %s", trigger_id)
    return result


def format_gtt_for_telegram(gtt_data: dict) -> str:
    """Format a GTT order for Telegram display."""
    status = gtt_data.get("status", "?")
    symbol = gtt_data.get("condition", {}).get("tradingsymbol", "?")
    exchange = gtt_data.get("condition", {}).get("exchange", "?")
    trigger_values = gtt_data.get("condition", {}).get("trigger_values", [])
    orders = gtt_data.get("orders", [])
    gtt_type = gtt_data.get("type", "?")

    lines = [f"GTT: {symbol} ({exchange})"]
    lines.append(f"Type: {gtt_type.upper()} | Status: {status.upper()}")

    if trigger_values:
        lines.append(f"Triggers: {', '.join(f'Rs {t:,.2f}' for t in trigger_values)}")

    for i, order in enumerate(orders):
        txn = order.get("transaction_type", "?")
        qty = order.get("quantity", 0)
        price = order.get("price", 0)
        lines.append(f"  Leg {i+1}: {txn} {qty}x @ Rs {price:,.2f}")

    return "\n".join(lines)

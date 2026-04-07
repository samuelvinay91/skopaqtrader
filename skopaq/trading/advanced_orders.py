"""Advanced order types via Kite Connect.

Supports:
    - AMO (After Market Orders) — place after 3:30 PM for next day
    - Bracket Orders — entry + target + stop-loss in one order
    - Cover Orders — entry + mandatory stop-loss
    - Basket Orders — execute multiple orders at once
    - Options Buying — directional trades with defined risk
    - Futures — NIFTY/BANKNIFTY/stock futures
    - Mutual Funds — SIP and lumpsum via Kite MF
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)


# ── AMO (After Market Orders) ────────────────────────────────────────────────


async def place_amo(
    kite_client,
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    exchange: str = "NSE",
    product: str = "CNC",
) -> dict:
    """Place an After Market Order — executes at next day's open.

    AMO orders can be placed between 3:30 PM and 9:00 AM.
    They participate in the pre-open auction at 9:00-9:15 AM.
    """
    order_id = await asyncio.to_thread(
        kite_client._kite.place_order,
        variety="amo",
        exchange=exchange,
        tradingsymbol=symbol,
        transaction_type=side.upper(),
        quantity=quantity,
        product=product,
        order_type="LIMIT",
        price=price,
    )

    logger.info("AMO placed: %s %s %sx @ %s", side, symbol, quantity, price)

    # Auto-notify
    try:
        from skopaq.notifications import notify

        await notify(
            f"AMO Order Placed\n\n"
            f"{side.upper()} {symbol}\n"
            f"Qty: {quantity} @ Rs {price:,.2f}\n"
            f"Executes: Next market open (9:15 AM)\n"
            f"Order: {order_id}"
        )
    except Exception:
        pass

    return {"order_id": str(order_id), "variety": "amo"}


# ── Bracket Orders ──────────────────────────────────────────────────────────


async def place_bracket_order(
    kite_client,
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    stoploss: float,
    target: float,
    trailing_stoploss: float = 0,
    exchange: str = "NSE",
) -> dict:
    """Place a Bracket Order — entry + target + stop-loss in one order.

    All three legs are managed by the exchange. Intraday only (MIS product).
    The position is automatically squared off at 3:20 PM if not exited.

    Args:
        stoploss: Stop-loss distance from entry (absolute points, not price).
        target: Target distance from entry (absolute points).
        trailing_stoploss: Trailing SL distance (0 = disabled).
    """
    order_id = await asyncio.to_thread(
        kite_client._kite.place_order,
        variety="bo",
        exchange=exchange,
        tradingsymbol=symbol,
        transaction_type=side.upper(),
        quantity=quantity,
        product="MIS",  # Bracket orders are always intraday
        order_type="LIMIT",
        price=price,
        stoploss=stoploss,
        squareoff=target,
        trailing_stoploss=trailing_stoploss if trailing_stoploss else None,
    )

    logger.info(
        "Bracket order: %s %s %sx @ %s SL=%s TGT=%s",
        side, symbol, quantity, price, stoploss, target,
    )

    try:
        from skopaq.notifications import notify

        await notify(
            f"Bracket Order Placed\n\n"
            f"{side.upper()} {symbol}\n"
            f"Entry: Rs {price:,.2f}\n"
            f"Stop Loss: Rs {price - stoploss if side == 'BUY' else price + stoploss:,.2f} "
            f"({stoploss} pts)\n"
            f"Target: Rs {price + target if side == 'BUY' else price - target:,.2f} "
            f"({target} pts)\n"
            f"Type: Intraday (MIS)\n"
            f"Order: {order_id}"
        )
    except Exception:
        pass

    return {"order_id": str(order_id), "variety": "bo"}


# ── Cover Orders ────────────────────────────────────────────────────────────


async def place_cover_order(
    kite_client,
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    trigger_price: float,
    exchange: str = "NSE",
) -> dict:
    """Place a Cover Order — entry + mandatory stop-loss.

    Reduced margin compared to regular MIS. Intraday only.

    Args:
        trigger_price: Stop-loss trigger price (absolute price).
    """
    order_id = await asyncio.to_thread(
        kite_client._kite.place_order,
        variety="co",
        exchange=exchange,
        tradingsymbol=symbol,
        transaction_type=side.upper(),
        quantity=quantity,
        product="MIS",
        order_type="LIMIT",
        price=price,
        trigger_price=trigger_price,
    )

    logger.info("Cover order: %s %s %sx @ %s SL=%s", side, symbol, quantity, price, trigger_price)

    try:
        from skopaq.notifications import notify

        await notify(
            f"Cover Order Placed\n\n"
            f"{side.upper()} {symbol}\n"
            f"Entry: Rs {price:,.2f}\n"
            f"Stop Loss: Rs {trigger_price:,.2f}\n"
            f"Type: Intraday (MIS)\n"
            f"Order: {order_id}"
        )
    except Exception:
        pass

    return {"order_id": str(order_id), "variety": "co"}


# ── Basket Orders ───────────────────────────────────────────────────────────


async def place_basket_orders(
    kite_client,
    orders: list[dict],
) -> list[dict]:
    """Place multiple orders as a basket.

    Each order dict should have:
        symbol, side, quantity, price, exchange (default NSE), product (default CNC)

    Returns list of order results.
    """
    results = []
    for o in orders:
        try:
            order_id = await asyncio.to_thread(
                kite_client._kite.place_order,
                variety="regular",
                exchange=o.get("exchange", "NSE"),
                tradingsymbol=o["symbol"],
                transaction_type=o["side"].upper(),
                quantity=o["quantity"],
                product=o.get("product", "CNC"),
                order_type="MARKET" if not o.get("price") else "LIMIT",
                price=o.get("price"),
            )
            results.append({
                "symbol": o["symbol"],
                "order_id": str(order_id),
                "status": "PLACED",
            })
        except Exception as exc:
            results.append({
                "symbol": o["symbol"],
                "order_id": "",
                "status": f"FAILED: {exc}",
            })

    # Notify
    try:
        from skopaq.notifications import notify

        lines = [f"Basket Order ({len(orders)} stocks)\n"]
        for r in results:
            emoji = "✅" if r["status"] == "PLACED" else "❌"
            lines.append(f"{emoji} {r['symbol']}: {r['status']}")
        await notify("\n".join(lines))
    except Exception:
        pass

    return results


# ── Options Buying ──────────────────────────────────────────────────────────


async def buy_option(
    kite_client,
    tradingsymbol: str,
    quantity: int,
    price: float = 0,
    exchange: str = "NFO",
    product: str = "NRML",
) -> dict:
    """Buy an option contract (directional trade with defined risk).

    Max loss = premium paid. No margin requirement beyond premium.

    Args:
        tradingsymbol: Full symbol (e.g., NIFTY2641323200CE).
        quantity: Number of lots × lot_size.
        price: Limit price (0 = market order).
        product: NRML (carry overnight) or MIS (intraday).
    """
    order_id = await asyncio.to_thread(
        kite_client._kite.place_order,
        variety="regular",
        exchange=exchange,
        tradingsymbol=tradingsymbol,
        transaction_type="BUY",
        quantity=quantity,
        product=product,
        order_type="MARKET" if not price else "LIMIT",
        price=price if price else None,
    )

    logger.info("Option BUY: %s %sx @ %s", tradingsymbol, quantity, price or "MARKET")

    try:
        from skopaq.notifications import notify

        await notify(
            f"Option BUY Placed\n\n"
            f"Contract: {tradingsymbol}\n"
            f"Qty: {quantity}\n"
            f"Price: {'MARKET' if not price else f'Rs {price:,.2f}'}\n"
            f"Max Loss: Premium paid\n"
            f"Order: {order_id}"
        )
    except Exception:
        pass

    return {"order_id": str(order_id), "type": "OPTION_BUY"}


# ── Futures ─────────────────────────────────────────────────────────────────


async def trade_futures(
    kite_client,
    symbol: str,
    side: str,
    quantity: int,
    price: float = 0,
    product: str = "NRML",
) -> dict:
    """Trade futures contracts (NIFTY/BANKNIFTY/stock futures).

    Args:
        symbol: Futures tradingsymbol (e.g., NIFTY26APR, NIFTYFUT).
        side: BUY or SELL.
        quantity: Number of lots × lot_size.
        price: Limit price (0 = market).
        product: NRML (overnight) or MIS (intraday, lower margin).
    """
    order_id = await asyncio.to_thread(
        kite_client._kite.place_order,
        variety="regular",
        exchange="NFO",
        tradingsymbol=symbol,
        transaction_type=side.upper(),
        quantity=quantity,
        product=product,
        order_type="MARKET" if not price else "LIMIT",
        price=price if price else None,
    )

    logger.info("Futures %s: %s %sx @ %s", side, symbol, quantity, price or "MARKET")

    try:
        from skopaq.notifications import notify

        await notify(
            f"Futures {side.upper()} Placed\n\n"
            f"Contract: {symbol}\n"
            f"Qty: {quantity}\n"
            f"Price: {'MARKET' if not price else f'Rs {price:,.2f}'}\n"
            f"Product: {product}\n"
            f"Order: {order_id}"
        )
    except Exception:
        pass

    return {"order_id": str(order_id), "type": "FUTURES"}


# ── Mutual Funds ────────────────────────────────────────────────────────────


async def place_mf_order(
    kite_client,
    tradingsymbol: str,
    amount: float,
    transaction_type: str = "BUY",
) -> dict:
    """Place a mutual fund lumpsum order.

    Args:
        tradingsymbol: MF tradingsymbol (e.g., INF846K01DP8 for UTI Nifty 50).
        amount: Investment amount in INR.
        transaction_type: BUY or SELL (redeem).
    """
    order_id = await asyncio.to_thread(
        kite_client._kite.place_mf_order,
        tradingsymbol=tradingsymbol,
        transaction_type=transaction_type.upper(),
        amount=amount,
    )

    logger.info("MF order: %s %s Rs %s", transaction_type, tradingsymbol, amount)

    try:
        from skopaq.notifications import notify

        await notify(
            f"Mutual Fund Order\n\n"
            f"{transaction_type.upper()} {tradingsymbol}\n"
            f"Amount: Rs {amount:,.2f}\n"
            f"Order: {order_id}"
        )
    except Exception:
        pass

    return {"order_id": str(order_id), "type": "MF_LUMPSUM"}


async def place_mf_sip(
    kite_client,
    tradingsymbol: str,
    amount: float,
    frequency: str = "monthly",
    instalment_day: int = 1,
    instalments: int = -1,
) -> dict:
    """Start a Systematic Investment Plan (SIP).

    Args:
        tradingsymbol: MF tradingsymbol.
        amount: SIP amount per instalment.
        frequency: monthly, weekly, etc.
        instalment_day: Day of month (1-28).
        instalments: Number of instalments (-1 = perpetual).
    """
    sip_id = await asyncio.to_thread(
        kite_client._kite.place_mf_sip,
        tradingsymbol=tradingsymbol,
        amount=amount,
        frequency=frequency,
        instalment_day=instalment_day,
        instalments=instalments,
    )

    logger.info("SIP started: %s Rs %s %s", tradingsymbol, amount, frequency)

    try:
        from skopaq.notifications import notify

        await notify(
            f"SIP Started\n\n"
            f"Fund: {tradingsymbol}\n"
            f"Amount: Rs {amount:,.2f} {frequency}\n"
            f"Day: {instalment_day}th of month\n"
            f"SIP ID: {sip_id}"
        )
    except Exception:
        pass

    return {"sip_id": str(sip_id), "type": "MF_SIP"}


async def list_mf_holdings(kite_client) -> list[dict]:
    """List mutual fund holdings."""
    holdings = await asyncio.to_thread(kite_client._kite.mf_holdings)
    return holdings or []


async def list_mf_sips(kite_client) -> list[dict]:
    """List active SIPs."""
    sips = await asyncio.to_thread(kite_client._kite.mf_sips)
    return sips or []


async def get_mf_instruments(kite_client) -> list[dict]:
    """Get available mutual fund instruments."""
    instruments = await asyncio.to_thread(kite_client._kite.mf_instruments)
    return instruments or []

"""Option chain fetcher and processor via Kite Connect.

Fetches the full option chain for NIFTY/BANKNIFTY/stocks, filters by
expiry, and computes key metrics (IV, distance from spot, premium yield).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OptionContract:
    """A single option contract with computed metrics."""

    tradingsymbol: str
    instrument_token: int
    exchange: str
    strike: float
    option_type: str  # "CE" or "PE"
    expiry: date
    lot_size: int

    # Live data (populated from quote)
    ltp: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    volume: int = 0
    oi: int = 0
    iv: float = 0.0  # Implied volatility

    # Computed metrics
    spot_price: float = 0.0
    distance_pct: float = 0.0  # % away from spot (OTM distance)
    premium_yield_pct: float = 0.0  # Premium / margin required
    days_to_expiry: int = 0
    theta_estimate: float = 0.0  # Daily time decay estimate


@dataclass
class OptionChainData:
    """Complete option chain for a symbol."""

    symbol: str
    spot_price: float
    expiry: date
    calls: list[OptionContract] = field(default_factory=list)
    puts: list[OptionContract] = field(default_factory=list)
    lot_size: int = 1
    fetched_at: datetime = field(default_factory=datetime.utcnow)


async def fetch_option_chain(
    kite_client,
    symbol: str = "NIFTY",
    expiry_index: int = 0,  # 0 = current week, 1 = next week, etc.
) -> OptionChainData:
    """Fetch the option chain for a symbol via Kite Connect.

    Args:
        kite_client: Authenticated KiteClient instance.
        symbol: Underlying symbol (NIFTY, BANKNIFTY, RELIANCE, etc.).
        expiry_index: 0 = nearest expiry, 1 = next, etc.

    Returns:
        OptionChainData with all calls and puts for the selected expiry.
    """
    import asyncio

    # Get instruments for NFO exchange
    instruments = await asyncio.to_thread(
        kite_client._kite.instruments, "NFO"
    )

    # Filter for this symbol's options
    option_instruments = [
        i for i in instruments
        if i["name"] == symbol
        and i["instrument_type"] in ("CE", "PE")
        and i["expiry"] is not None
    ]

    if not option_instruments:
        raise ValueError(f"No options found for {symbol} on NFO")

    # Get unique expiries sorted
    expiries = sorted(set(i["expiry"] for i in option_instruments))
    if expiry_index >= len(expiries):
        expiry_index = 0

    selected_expiry = expiries[expiry_index]
    logger.info("Selected expiry: %s (index %d of %d)", selected_expiry, expiry_index, len(expiries))

    # Filter for selected expiry
    chain_instruments = [
        i for i in option_instruments if i["expiry"] == selected_expiry
    ]

    # Get spot price
    exchange_symbol = f"NSE:{symbol}" if symbol in ("NIFTY", "BANKNIFTY", "NIFTY 50", "NIFTY BANK") else f"NSE:{symbol}"
    # For indices, use the index quote
    if symbol in ("NIFTY", "NIFTY 50"):
        exchange_symbol = "NSE:NIFTY 50"
    elif symbol in ("BANKNIFTY", "NIFTY BANK"):
        exchange_symbol = "NSE:NIFTY BANK"

    spot_data = await asyncio.to_thread(kite_client._kite.ltp, [exchange_symbol])
    spot_price = list(spot_data.values())[0]["last_price"] if spot_data else 0

    # Get lot size
    lot_size = chain_instruments[0].get("lot_size", 1) if chain_instruments else 1

    # Filter strikes around spot price (±10% to avoid too many)
    lower = spot_price * 0.90
    upper = spot_price * 1.10
    chain_instruments = [
        i for i in chain_instruments
        if lower <= i["strike"] <= upper
    ]

    # Fetch quotes for all instruments in the chain
    instrument_tokens = [f"NFO:{i['tradingsymbol']}" for i in chain_instruments]

    # Kite API allows max ~500 instruments per quote call
    quotes = {}
    for batch_start in range(0, len(instrument_tokens), 200):
        batch = instrument_tokens[batch_start:batch_start + 200]
        batch_quotes = await asyncio.to_thread(kite_client._kite.quote, batch)
        quotes.update(batch_quotes)

    # Build option contracts
    calls = []
    puts = []
    days_to_expiry = (selected_expiry - date.today()).days

    for inst in chain_instruments:
        token_key = f"NFO:{inst['tradingsymbol']}"
        q = quotes.get(token_key, {})
        ohlc = q.get("ohlc", {})

        # OTM distance: positive = out-of-the-money, negative = in-the-money
        # CE is OTM when strike > spot; PE is OTM when strike < spot
        if inst["instrument_type"] == "CE":
            distance = ((inst["strike"] - spot_price) / spot_price) * 100
            is_otm = inst["strike"] > spot_price
        else:  # PE
            distance = ((spot_price - inst["strike"]) / spot_price) * 100
            is_otm = inst["strike"] < spot_price

        # Only include OTM strikes (ITM options shouldn't be sold naked)
        if not is_otm:
            continue

        contract = OptionContract(
            tradingsymbol=inst["tradingsymbol"],
            instrument_token=inst["instrument_token"],
            exchange="NFO",
            strike=inst["strike"],
            option_type=inst["instrument_type"],
            expiry=selected_expiry,
            lot_size=lot_size,
            ltp=q.get("last_price", 0),
            bid=q.get("depth", {}).get("buy", [{}])[0].get("price", 0) if q.get("depth") else 0,
            ask=q.get("depth", {}).get("sell", [{}])[0].get("price", 0) if q.get("depth") else 0,
            volume=q.get("volume", 0),
            oi=q.get("oi", 0),
            spot_price=spot_price,
            distance_pct=distance,  # Always positive for OTM
            days_to_expiry=max(days_to_expiry, 1),
            theta_estimate=q.get("last_price", 0) / max(days_to_expiry, 1),
        )

        if inst["instrument_type"] == "CE":
            calls.append(contract)
        else:
            puts.append(contract)

    # Sort by strike
    calls.sort(key=lambda x: x.strike)
    puts.sort(key=lambda x: x.strike)

    return OptionChainData(
        symbol=symbol,
        spot_price=spot_price,
        expiry=selected_expiry,
        calls=calls,
        puts=puts,
        lot_size=lot_size,
    )

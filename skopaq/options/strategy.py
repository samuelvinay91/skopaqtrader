"""AI-powered options strategy selector.

Analyzes the option chain and selects the optimal strikes for selling
based on distance from spot, premium yield, days to expiry, and risk.

Strategies:
    - Short Put (bullish) — sell OTM put, profit from theta
    - Short Call (bearish) — sell OTM call, profit from theta
    - Short Strangle (neutral) — sell both OTM put + call
    - Iron Condor (neutral) — strangle with protection wings
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from skopaq.options.chain import OptionChainData, OptionContract

logger = logging.getLogger(__name__)


@dataclass
class OptionTrade:
    """A recommended option trade with full risk metrics."""

    strategy: str  # "SHORT_PUT", "SHORT_CALL", "SHORT_STRANGLE"
    symbol: str
    expiry: str

    # Legs
    sell_contract: OptionContract
    sell_contract_2: Optional[OptionContract] = None  # For strangles

    # Risk metrics
    premium: float = 0.0  # Total premium collected
    max_profit: float = 0.0  # Premium × lot_size
    max_loss: float = 0.0  # Strike distance × lot_size (without stop)
    breakeven: float = 0.0
    margin_required: float = 0.0  # Approximate

    # AI assessment
    win_probability_pct: float = 0.0
    risk_reward: str = ""
    confidence: int = 0  # 0-100
    reasoning: str = ""


def select_short_put(
    chain: OptionChainData,
    min_distance_pct: float = 3.0,
    max_distance_pct: float = 8.0,
    min_premium: float = 5.0,
) -> Optional[OptionTrade]:
    """Select the best OTM put to sell.

    Criteria:
    - Strike is 3-8% below spot (OTM sweet spot)
    - Premium is at least ₹5
    - Highest premium yield among qualifying strikes
    - Good liquidity (volume > 0 or OI > 100)

    Args:
        chain: Option chain data with puts populated.
        min_distance_pct: Minimum distance from spot (%).
        max_distance_pct: Maximum distance from spot (%).
        min_premium: Minimum premium in ₹.

    Returns:
        OptionTrade recommendation or None.
    """
    candidates = [
        p for p in chain.puts
        if min_distance_pct <= p.distance_pct <= max_distance_pct
        and p.ltp >= min_premium
        and (p.volume > 0 or p.oi > 100)
    ]

    if not candidates:
        # Widen criteria
        candidates = [
            p for p in chain.puts
            if p.distance_pct >= 2.0
            and p.ltp >= 1.0
        ]

    if not candidates:
        return None

    # Score: premium yield weighted by distance (further = safer)
    def score(c: OptionContract) -> float:
        return c.ltp * c.distance_pct

    best = max(candidates, key=score)

    premium = best.ltp
    max_profit = premium * chain.lot_size
    max_loss = best.strike * chain.lot_size  # Theoretical (stock goes to 0)
    breakeven = best.strike - premium

    # Win probability estimate based on distance
    # Simple model: P(OTM at expiry) ≈ 1 - N(distance/volatility)
    # Rough heuristic: 3% OTM ≈ 70%, 5% OTM ≈ 80%, 8% OTM ≈ 90%
    win_pct = min(50 + best.distance_pct * 7, 95)

    # Margin estimate (rough: ~15-20% of underlying value for index options)
    margin = chain.spot_price * chain.lot_size * 0.15

    return OptionTrade(
        strategy="SHORT_PUT",
        symbol=chain.symbol,
        expiry=str(chain.expiry),
        sell_contract=best,
        premium=premium,
        max_profit=max_profit,
        max_loss=max_profit * 3,  # Using stop-loss at 3x premium
        breakeven=breakeven,
        margin_required=margin,
        win_probability_pct=round(win_pct, 1),
        risk_reward=f"1:{(max_profit / (max_profit * 3)):.1f}" if max_profit else "N/A",
        confidence=int(min(win_pct - 10, 85)),
        reasoning=(
            f"Sell {best.tradingsymbol} at ₹{premium:.2f}. "
            f"Strike {best.strike:.0f} is {best.distance_pct:.1f}% OTM. "
            f"Collect ₹{max_profit:,.0f} premium ({chain.lot_size} lot). "
            f"Theta decay: ~₹{best.theta_estimate:.2f}/day. "
            f"DTE: {best.days_to_expiry}. "
            f"Win probability: ~{win_pct:.0f}%."
        ),
    )


def select_short_call(
    chain: OptionChainData,
    min_distance_pct: float = 3.0,
    max_distance_pct: float = 8.0,
    min_premium: float = 5.0,
) -> Optional[OptionTrade]:
    """Select the best OTM call to sell. Same logic as short_put but for calls."""
    candidates = [
        c for c in chain.calls
        if min_distance_pct <= c.distance_pct <= max_distance_pct
        and c.ltp >= min_premium
        and (c.volume > 0 or c.oi > 100)
    ]

    if not candidates:
        candidates = [
            c for c in chain.calls
            if c.distance_pct >= 2.0
            and c.ltp >= 1.0
        ]

    if not candidates:
        return None

    def score(c: OptionContract) -> float:
        return c.ltp * c.distance_pct

    best = max(candidates, key=score)

    premium = best.ltp
    max_profit = premium * chain.lot_size
    breakeven = best.strike + premium

    win_pct = min(50 + best.distance_pct * 7, 95)
    margin = chain.spot_price * chain.lot_size * 0.15

    return OptionTrade(
        strategy="SHORT_CALL",
        symbol=chain.symbol,
        expiry=str(chain.expiry),
        sell_contract=best,
        premium=premium,
        max_profit=max_profit,
        max_loss=max_profit * 3,
        breakeven=breakeven,
        margin_required=margin,
        win_probability_pct=round(win_pct, 1),
        risk_reward=f"1:{(max_profit / (max_profit * 3)):.1f}" if max_profit else "N/A",
        confidence=int(min(win_pct - 10, 85)),
        reasoning=(
            f"Sell {best.tradingsymbol} at ₹{premium:.2f}. "
            f"Strike {best.strike:.0f} is {best.distance_pct:.1f}% OTM. "
            f"Collect ₹{max_profit:,.0f} premium ({chain.lot_size} lot). "
            f"Theta decay: ~₹{best.theta_estimate:.2f}/day. "
            f"DTE: {best.days_to_expiry}. "
            f"Win probability: ~{win_pct:.0f}%."
        ),
    )


def select_short_strangle(
    chain: OptionChainData,
    min_distance_pct: float = 4.0,
    max_distance_pct: float = 8.0,
    min_premium: float = 3.0,
) -> Optional[OptionTrade]:
    """Select a short strangle (sell OTM put + OTM call)."""
    put_trade = select_short_put(chain, min_distance_pct, max_distance_pct, min_premium)
    call_trade = select_short_call(chain, min_distance_pct, max_distance_pct, min_premium)

    if not put_trade or not call_trade:
        return None

    total_premium = put_trade.premium + call_trade.premium
    max_profit = total_premium * chain.lot_size
    margin = chain.spot_price * chain.lot_size * 0.20  # Higher margin for strangle

    combined_win_pct = put_trade.win_probability_pct * call_trade.win_probability_pct / 100

    return OptionTrade(
        strategy="SHORT_STRANGLE",
        symbol=chain.symbol,
        expiry=str(chain.expiry),
        sell_contract=put_trade.sell_contract,
        sell_contract_2=call_trade.sell_contract,
        premium=total_premium,
        max_profit=max_profit,
        max_loss=max_profit * 3,
        breakeven=0,  # Two breakevens for strangle
        margin_required=margin,
        win_probability_pct=round(combined_win_pct, 1),
        risk_reward=f"1:{(max_profit / (max_profit * 3)):.1f}" if max_profit else "N/A",
        confidence=int(min(combined_win_pct - 5, 80)),
        reasoning=(
            f"Sell {put_trade.sell_contract.tradingsymbol} at ₹{put_trade.premium:.2f} + "
            f"{call_trade.sell_contract.tradingsymbol} at ₹{call_trade.premium:.2f}. "
            f"Total premium: ₹{total_premium:.2f} × {chain.lot_size} = ₹{max_profit:,.0f}. "
            f"Put {put_trade.sell_contract.distance_pct:.1f}% OTM, "
            f"Call {call_trade.sell_contract.distance_pct:.1f}% OTM. "
            f"DTE: {put_trade.sell_contract.days_to_expiry}. "
            f"Combined win probability: ~{combined_win_pct:.0f}%."
        ),
    )


def format_trade_for_telegram(trade: OptionTrade) -> str:
    """Format an option trade recommendation for Telegram."""
    lines = [f"OPTIONS TRADE: {trade.strategy.replace('_', ' ')}\n"]

    lines.append(f"Symbol: {trade.symbol}")
    lines.append(f"Expiry: {trade.expiry}")
    lines.append("")

    if trade.sell_contract:
        lines.append(f"Sell: {trade.sell_contract.tradingsymbol}")
        lines.append(f"  Strike: {trade.sell_contract.strike:.0f} ({trade.sell_contract.option_type})")
        lines.append(f"  Premium: Rs {trade.sell_contract.ltp:.2f}")
        lines.append(f"  OTM Distance: {trade.sell_contract.distance_pct:.1f}%")

    if trade.sell_contract_2:
        lines.append("")
        lines.append(f"Sell: {trade.sell_contract_2.tradingsymbol}")
        lines.append(f"  Strike: {trade.sell_contract_2.strike:.0f} ({trade.sell_contract_2.option_type})")
        lines.append(f"  Premium: Rs {trade.sell_contract_2.ltp:.2f}")
        lines.append(f"  OTM Distance: {trade.sell_contract_2.distance_pct:.1f}%")

    lines.append("")
    lines.append(f"Max Profit: Rs {trade.max_profit:,.0f}")
    lines.append(f"Max Loss (with SL): Rs {trade.max_loss:,.0f}")
    lines.append(f"Margin Required: ~Rs {trade.margin_required:,.0f}")
    lines.append(f"Win Probability: {trade.win_probability_pct:.0f}%")
    lines.append(f"Confidence: {trade.confidence}%")
    lines.append("")
    lines.append(trade.reasoning)

    return "\n".join(lines)

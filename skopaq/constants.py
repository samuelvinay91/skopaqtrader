"""Immutable safety rules and market constants.

CRITICAL: These values can ONLY be changed by a human editing this file.
The learning engine, Strategy DNA, and all automated processes are forbidden
from modifying any value defined here.  Attempting to mutate a ``SafetyRules``
instance will raise ``FrozenInstanceError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time


# ── Immutable Safety Rules ──────────────────────────────────────────────────


@dataclass(frozen=True)
class SafetyRules:
    """Frozen safety limits enforced on every order.  Cannot be modified at runtime."""

    # Capital protection
    max_position_pct: float = 0.15  # Max 15% of capital per position
    max_daily_loss_pct: float = 0.03  # Stop trading at 3% daily loss
    max_weekly_loss_pct: float = 0.07  # Stop trading at 7% weekly loss
    max_monthly_loss_pct: float = 0.12  # Stop trading at 12% monthly loss

    # Position rules
    max_open_positions: int = 5
    max_lots_per_position: int = 5
    max_order_value_inr: float = 500_000.0
    max_orders_per_minute: int = 20

    # Stop-loss
    require_stop_loss: bool = True
    min_stop_loss_pct: float = 0.02  # At least 2% stop loss

    # Confidence gate
    min_confidence_pct: int = 0  # 0 = disabled; e.g., 40 to reject <40% signals

    # Forbidden actions
    no_naked_option_selling: bool = True

    # Timing
    market_hours_only: bool = True
    cool_down_after_loss_minutes: int = 15

    # Infrastructure
    auto_shutdown_on_api_failure_minutes: int = 5

    # Evolution guardrails (for learning engine)
    max_dna_updates_per_day: int = 1
    min_backtest_improvement_pct: float = 5.0
    mandatory_paper_days_for_new_strategy: int = 7
    human_approval_for_major_changes: bool = True
    max_parameter_change_per_evolution_pct: float = 20.0


# Singleton — import this, don't create new instances
SAFETY_RULES = SafetyRules()

# Paper-mode variant — relaxes timing and stop-loss so we can test anytime.
# Capital protection limits remain fully enforced even in paper mode.
PAPER_SAFETY_RULES = SafetyRules(
    market_hours_only=False,      # Allow trades outside market hours
    require_stop_loss=False,      # Upstream agents don't always set stop-loss
)

# Crypto live variant — 24/7 trading with tighter position limits
# (crypto is more volatile than Indian equities).
CRYPTO_SAFETY_RULES = SafetyRules(
    market_hours_only=False,       # 24/7 crypto markets
    require_stop_loss=False,
    max_position_pct=0.10,         # 10% max per position (vs 15% equity)
    max_daily_loss_pct=0.05,       # 5% daily loss limit (vs 3% equity)
    max_order_value_inr=50_000.0,  # Reinterpreted as USDT for crypto
)

# Crypto paper variant — relaxed for testing.
CRYPTO_PAPER_SAFETY_RULES = SafetyRules(
    market_hours_only=False,
    require_stop_loss=False,
    max_order_value_inr=50_000.0,
)


# Intraday (MIS) variant — strict market hours + mandatory EOD exit.
# MIS positions get squared off by the broker at 3:15 PM if not closed.
# We use tighter limits since intraday margin provides leverage.
INTRADAY_SAFETY_RULES = SafetyRules(
    market_hours_only=True,           # Must trade during NSE hours
    require_stop_loss=True,           # Mandatory for intraday
    min_stop_loss_pct=0.01,           # 1% min (tighter than delivery 2%)
    max_position_pct=0.20,            # 20% — MIS gets ~5x margin
    max_order_value_inr=500_000.0,    # Same cap, but margin makes it go further
    max_daily_loss_pct=0.02,          # 2% daily loss limit (tighter)
    cool_down_after_loss_minutes=10,  # Shorter cooldown for intraday
)

# Intraday paper variant — relaxed timing for testing outside market hours.
INTRADAY_PAPER_SAFETY_RULES = SafetyRules(
    market_hours_only=False,          # Test anytime
    require_stop_loss=False,          # Relaxed for paper
    max_position_pct=0.20,            # Same leverage limits
    max_daily_loss_pct=0.02,          # Same loss limit
)


# Daemon variant — tighter limits for fully autonomous unattended trading.
DAEMON_SAFETY_RULES = SafetyRules(
    max_open_positions=3,             # 3 vs 5: tighter for unattended
    max_order_value_inr=200_000.0,    # ₹2L vs ₹5L: lower cap
    max_orders_per_minute=5,          # 5 vs 20: slower pace
)

# Daemon paper variant — relaxed timing + stop-loss for testing.
DAEMON_PAPER_SAFETY_RULES = SafetyRules(
    market_hours_only=False,
    require_stop_loss=False,
    max_open_positions=3,
)


# ── Market Hours (IST) ──────────────────────────────────────────────────────

NSE_PRE_OPEN_START = time(9, 0)
NSE_PRE_OPEN_END = time(9, 8)
NSE_MARKET_OPEN = time(9, 15)
NSE_MARKET_CLOSE = time(15, 30)
NSE_POST_CLOSE = time(15, 40)

# ── Exchange Constants ──────────────────────────────────────────────────────

EXCHANGE_NSE = "NSE"
EXCHANGE_BSE = "BSE"
VALID_EXCHANGES = frozenset({EXCHANGE_NSE, EXCHANGE_BSE})

# ── Order Types ─────────────────────────────────────────────────────────────

ORDER_TYPE_MARKET = "MARKET"
ORDER_TYPE_LIMIT = "LIMIT"
ORDER_TYPE_SL = "SL"
ORDER_TYPE_SLM = "SL-M"
VALID_ORDER_TYPES = frozenset({ORDER_TYPE_MARKET, ORDER_TYPE_LIMIT, ORDER_TYPE_SL, ORDER_TYPE_SLM})

# ── Product Types ───────────────────────────────────────────────────────────

PRODUCT_CNC = "CNC"  # Cash & Carry (delivery)
PRODUCT_MIS = "MIS"  # Margin Intraday Settlement
PRODUCT_NRML = "NRML"  # Normal (F&O carry forward)
VALID_PRODUCTS = frozenset({PRODUCT_CNC, PRODUCT_MIS, PRODUCT_NRML})

# ── Sides ───────────────────────────────────────────────────────────────────

SIDE_BUY = "BUY"
SIDE_SELL = "SELL"
VALID_SIDES = frozenset({SIDE_BUY, SIDE_SELL})

# ── Market Event Blackouts ──────────────────────────────────────────────────

BLACKOUT_EVENTS = frozenset({
    "rbi_policy_day",
    "union_budget_day",
    "general_election_results",
})

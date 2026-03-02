"""Pydantic models for Supabase database records.

These map 1:1 with the tables in ``supabase/migrations/001_initial.sql``.
Used by repositories for typed insert/select operations.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TradeRecord(BaseModel):
    """Row in the ``trades`` table."""

    id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    symbol: str
    exchange: str = "NSE"
    side: str
    quantity: int
    price: Optional[Decimal] = None
    order_type: str = "MARKET"
    product: str = "CNC"
    order_id: Optional[str] = None
    status: str = "PENDING"
    is_paper: bool = True

    signal_source: Optional[str] = None
    agent_decision: dict[str, Any] = Field(default_factory=dict)
    model_signals: dict[str, Any] = Field(default_factory=dict)
    consensus_score: Optional[int] = None
    entry_reason: Optional[str] = None
    exit_reason: Optional[str] = None

    pnl: Optional[Decimal] = None
    brokerage: Decimal = Decimal("5.00")
    fill_price: Optional[Decimal] = None
    slippage: Optional[Decimal] = None

    strategy_version: Optional[str] = None
    nifty_level: Optional[Decimal] = None
    india_vix: Optional[Decimal] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StrategyVersionRecord(BaseModel):
    """Row in the ``strategy_versions`` table."""

    id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    version: str
    dna_yaml: str
    active: bool = False
    backtest_sharpe: Optional[Decimal] = None
    backtest_win_rate: Optional[Decimal] = None
    backtest_max_dd: Optional[Decimal] = None
    reason: Optional[str] = None
    parent_version: Optional[str] = None
    approved_by: Optional[str] = None
    created_at: Optional[datetime] = None


class ModelPredictionRecord(BaseModel):
    """Row in the ``model_predictions`` table."""

    id: Optional[UUID] = None
    trade_id: Optional[UUID] = None
    model_name: str
    prediction: Optional[str] = None
    confidence: Optional[Decimal] = None
    actual_outcome: Optional[str] = None
    correct: Optional[bool] = None
    latency_ms: Optional[int] = None
    cost_usd: Optional[Decimal] = None
    created_at: Optional[datetime] = None


class HealingEventRecord(BaseModel):
    """Row in the ``healing_events`` table."""

    id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    component: str
    event_type: str
    description: Optional[str] = None
    action_taken: Optional[str] = None
    resolved: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class DailySnapshotRecord(BaseModel):
    """Row in the ``daily_snapshots`` table."""

    id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    date: date
    portfolio_value: Decimal
    cash: Decimal
    day_pnl: Decimal = Decimal("0")
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    max_drawdown_pct: Optional[Decimal] = None
    strategy_version: Optional[str] = None
    model_accuracy: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None

-- ============================================================================
-- SkopaqTrader — Initial Database Schema
-- ============================================================================
-- Applied via: supabase db push  (or Supabase dashboard SQL editor)
-- All tables use RLS.  Backend uses service_role key to bypass RLS.
-- Frontend uses anon key + auth.uid() scoped policies.
-- ============================================================================

-- ── trades ──────────────────────────────────────────────────────────────────
-- Every order placed (paper + live), with full agent decision context.

CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) DEFAULT auth.uid(),
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL CHECK (exchange IN ('NSE', 'BSE')),
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    price DECIMAL(12,2),
    order_type TEXT NOT NULL CHECK (order_type IN ('MARKET', 'LIMIT', 'SL', 'SL-M')),
    product TEXT NOT NULL DEFAULT 'CNC' CHECK (product IN ('CNC', 'MIS', 'NRML')),
    order_id TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'PENDING',
    is_paper BOOLEAN NOT NULL DEFAULT true,

    -- Agent context
    signal_source TEXT,                   -- scanner / manual / agent
    agent_decision JSONB DEFAULT '{}',    -- Full agent state snapshot
    model_signals JSONB DEFAULT '{}',     -- Per-model recommendations
    consensus_score INTEGER CHECK (consensus_score BETWEEN 0 AND 100),
    entry_reason TEXT,
    exit_reason TEXT,

    -- P&L
    pnl DECIMAL(12,2),
    brokerage DECIMAL(8,2) DEFAULT 5.00,
    fill_price DECIMAL(12,2),
    slippage DECIMAL(8,4),

    -- Strategy context
    strategy_version TEXT,
    nifty_level DECIMAL(10,2),
    india_vix DECIMAL(6,2),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── strategy_versions ───────────────────────────────────────────────────────
-- DNA YAML snapshots for the self-learning engine.

CREATE TABLE IF NOT EXISTS strategy_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) DEFAULT auth.uid(),
    version TEXT NOT NULL UNIQUE,
    dna_yaml TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT false,
    backtest_sharpe DECIMAL(6,3),
    backtest_win_rate DECIMAL(6,3),
    backtest_max_dd DECIMAL(6,3),
    reason TEXT,
    parent_version TEXT,
    approved_by TEXT,                      -- 'human' or 'auto'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── model_predictions ───────────────────────────────────────────────────────
-- Per-model accuracy tracking for multi-model tiering.

CREATE TABLE IF NOT EXISTS model_predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id UUID REFERENCES trades(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    prediction TEXT,                       -- BUY / SELL / HOLD
    confidence DECIMAL(5,2),
    actual_outcome TEXT,
    correct BOOLEAN,
    latency_ms INTEGER,
    cost_usd DECIMAL(8,4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── healing_events ──────────────────────────────────────────────────────────
-- Self-healing log for infrastructure monitoring.

CREATE TABLE IF NOT EXISTS healing_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) DEFAULT auth.uid(),
    component TEXT NOT NULL,               -- broker / websocket / llm / scheduler
    event_type TEXT NOT NULL,              -- error / warning / recovery / circuit_break
    description TEXT,
    action_taken TEXT,
    resolved BOOLEAN NOT NULL DEFAULT true,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── daily_snapshots ─────────────────────────────────────────────────────────
-- End-of-day portfolio state for performance tracking.

CREATE TABLE IF NOT EXISTS daily_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) DEFAULT auth.uid(),
    date DATE NOT NULL,
    portfolio_value DECIMAL(14,2) NOT NULL,
    cash DECIMAL(14,2) NOT NULL,
    day_pnl DECIMAL(12,2) NOT NULL DEFAULT 0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    winning_trades INTEGER NOT NULL DEFAULT 0,
    losing_trades INTEGER NOT NULL DEFAULT 0,
    max_drawdown_pct DECIMAL(6,3),
    strategy_version TEXT,
    model_accuracy JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, date)
);


-- ============================================================================
-- Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_trades_symbol_date ON trades(symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_user ON trades(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_paper ON trades(is_paper, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_predictions_model ON model_predictions(model_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_trade ON model_predictions(trade_id);

CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(user_id, date DESC);

CREATE INDEX IF NOT EXISTS idx_healing_component ON healing_events(component, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_strategy_active ON strategy_versions(active) WHERE active = true;


-- ============================================================================
-- Row Level Security
-- ============================================================================

ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE strategy_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_predictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE healing_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_snapshots ENABLE ROW LEVEL SECURITY;

-- Users can only see their own data
CREATE POLICY "users_own_trades" ON trades
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "users_own_strategies" ON strategy_versions
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "users_own_predictions" ON model_predictions
    FOR ALL USING (
        trade_id IN (SELECT id FROM trades WHERE user_id = auth.uid())
    );

CREATE POLICY "users_own_healing" ON healing_events
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "users_own_snapshots" ON daily_snapshots
    FOR ALL USING (auth.uid() = user_id);


-- ============================================================================
-- Updated-at trigger
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trades_updated_at
    BEFORE UPDATE ON trades
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

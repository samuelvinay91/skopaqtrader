-- ============================================================================
-- SkopaqTrader — Agent Memory Persistence + Trade Lifecycle
-- ============================================================================
-- Applied via: supabase db push  (or Supabase dashboard SQL editor)
-- Adds persistent storage for agent memories (self-evolution) and
-- trade lifecycle tracking for automated reflection.
-- ============================================================================

-- ── agent_memories ────────────────────────────────────────────────────────
-- One row per agent role per user.  documents + recommendations are JSONB
-- arrays mirroring FinancialSituationMemory's in-memory lists.
-- BM25 index is rebuilt at runtime from documents (not stored).

CREATE TABLE IF NOT EXISTS agent_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) DEFAULT auth.uid(),
    role TEXT NOT NULL,                          -- 'bull_memory', 'bear_memory', etc.
    documents JSONB NOT NULL DEFAULT '[]'::jsonb,       -- List[str] situations
    recommendations JSONB NOT NULL DEFAULT '[]'::jsonb, -- List[str] lessons
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, role)
);

-- ── trades table extensions ───────────────────────────────────────────────
-- Link SELL trades back to their opening BUY for P&L tracking.

ALTER TABLE trades ADD COLUMN IF NOT EXISTS opening_trade_id UUID REFERENCES trades(id);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;


-- ============================================================================
-- Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_memories_user_role ON agent_memories(user_id, role);

-- Fast lookup of open BUY positions (SELL-side lifecycle matching)
CREATE INDEX IF NOT EXISTS idx_trades_open_buys
    ON trades(symbol, created_at DESC)
    WHERE side = 'BUY' AND closed_at IS NULL;


-- ============================================================================
-- Row Level Security
-- ============================================================================

ALTER TABLE agent_memories ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users_own_memories" ON agent_memories
    FOR ALL USING (auth.uid() = user_id);


-- ============================================================================
-- Updated-at trigger (reuses function from 001_initial.sql)
-- ============================================================================

CREATE TRIGGER agent_memories_updated_at
    BEFORE UPDATE ON agent_memories
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

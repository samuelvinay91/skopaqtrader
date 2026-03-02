"""Tests for MemoryStore — agent memory persistence via Supabase.

Validates the save/load roundtrip, FIFO cap enforcement, graceful
degradation on empty DB, and BM25 index rebuilding after load.

All tests mock the Supabase client — no real DB calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from skopaq.db.models import AgentMemoryRecord
from skopaq.memory.store import MEMORY_ROLES, MemoryStore


# ── Stubs ────────────────────────────────────────────────────────────────────


@dataclass
class FakeMemory:
    """Lightweight stub for upstream FinancialSituationMemory.

    Mimics the three attributes MemoryStore interacts with:
    - documents: list[str]
    - recommendations: list[str]
    - _rebuild_index(): called after mutating documents
    """

    documents: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    index_rebuilt: bool = False

    def _rebuild_index(self) -> None:
        self.index_rebuilt = True


class FakeGraph:
    """Stub for upstream TradingAgentsGraph with 5 memory attributes."""

    def __init__(self) -> None:
        self.bull_memory = FakeMemory()
        self.bear_memory = FakeMemory()
        self.trader_memory = FakeMemory()
        self.invest_judge_memory = FakeMemory()
        self.risk_manager_memory = FakeMemory()

    def get_memory(self, role: str) -> FakeMemory:
        return getattr(self, role)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_memory_record(role: str, docs: list[str], recs: list[str]) -> dict:
    """Build a raw row dict as Supabase would return."""
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "user_id": None,
        "role": role,
        "documents": docs,
        "recommendations": recs,
        "updated_at": "2025-06-01T00:00:00Z",
    }


def _make_mock_client(memory_rows: list[dict] | None = None) -> MagicMock:
    """Create a mock Supabase client with configurable memory table responses.

    Args:
        memory_rows: List of raw row dicts for get_all_roles().
                     None means empty DB (no rows).
    """
    client = MagicMock()
    table = MagicMock()
    client.table.return_value = table

    # Chain: table("agent_memories").select("*").execute()
    select_chain = MagicMock()
    table.select.return_value = select_chain
    execute_result = MagicMock()
    execute_result.data = memory_rows or []
    select_chain.execute.return_value = execute_result

    # Chain: table("agent_memories").upsert(data).execute()
    # The mock echoes back the input data so AgentMemoryRecord(**row) succeeds
    def upsert_side_effect(data, **kwargs):
        chain = MagicMock()
        result = MagicMock()
        result.data = [data]  # Echo back input (has role, documents, etc.)
        chain.execute.return_value = result
        return chain

    table.upsert.side_effect = upsert_side_effect

    return client


# ── Tests ────────────────────────────────────────────────────────────────────


class TestMemoryStoreLoad:
    """Tests for MemoryStore.load()."""

    def test_load_empty_db(self):
        """Load when no rows exist — memories should stay empty."""
        client = _make_mock_client(memory_rows=[])
        store = MemoryStore(client, max_entries=50)
        graph = FakeGraph()

        total = store.load(graph)

        assert total == 0
        for role in MEMORY_ROLES:
            mem = graph.get_memory(role)
            assert mem.documents == []
            assert mem.recommendations == []
            assert not mem.index_rebuilt

    def test_load_populates_memories(self):
        """Load from Supabase — documents and recommendations mutated in place."""
        rows = [
            _make_memory_record("bull_memory", ["doc1", "doc2"], ["rec1", "rec2"]),
            _make_memory_record("bear_memory", ["doc3"], ["rec3"]),
        ]
        client = _make_mock_client(memory_rows=rows)
        store = MemoryStore(client, max_entries=50)
        graph = FakeGraph()

        total = store.load(graph)

        assert total == 3  # 2 + 1
        assert graph.bull_memory.documents == ["doc1", "doc2"]
        assert graph.bull_memory.recommendations == ["rec1", "rec2"]
        assert graph.bear_memory.documents == ["doc3"]
        assert graph.bear_memory.recommendations == ["rec3"]
        # Untouched roles stay empty
        assert graph.trader_memory.documents == []

    def test_load_rebuilds_bm25_index(self):
        """After loading, _rebuild_index() should be called on populated memories."""
        rows = [
            _make_memory_record("trader_memory", ["doc1"], ["rec1"]),
        ]
        client = _make_mock_client(memory_rows=rows)
        store = MemoryStore(client, max_entries=50)
        graph = FakeGraph()

        store.load(graph)

        assert graph.trader_memory.index_rebuilt is True
        # Roles with no data should NOT have index rebuilt
        assert graph.bull_memory.index_rebuilt is False

    def test_load_skips_mismatched_lengths(self):
        """If documents and recommendations have different lengths, skip that role."""
        rows = [
            _make_memory_record("bull_memory", ["doc1", "doc2"], ["rec1"]),  # Mismatch!
            _make_memory_record("bear_memory", ["doc3"], ["rec3"]),  # OK
        ]
        client = _make_mock_client(memory_rows=rows)
        store = MemoryStore(client, max_entries=50)
        graph = FakeGraph()

        total = store.load(graph)

        assert total == 1  # Only bear_memory loaded
        assert graph.bull_memory.documents == []  # Skipped
        assert graph.bear_memory.documents == ["doc3"]

    def test_load_survives_supabase_error(self):
        """If Supabase throws, load returns 0 gracefully."""
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table
        table.select.side_effect = Exception("Connection refused")

        store = MemoryStore(client, max_entries=50)
        graph = FakeGraph()

        total = store.load(graph)

        assert total == 0

    def test_load_mutates_in_place(self):
        """Verify that load mutates the SAME memory objects, not replacements.

        This is critical because upstream graph passes memory objects by reference
        to agent node closures — replacing objects would break the reference chain.
        """
        rows = [
            _make_memory_record("bull_memory", ["doc1"], ["rec1"]),
        ]
        client = _make_mock_client(memory_rows=rows)
        store = MemoryStore(client, max_entries=50)
        graph = FakeGraph()

        # Capture reference BEFORE load
        original_mem = graph.bull_memory

        store.load(graph)

        # After load, the attribute should still be the SAME object
        assert graph.bull_memory is original_mem
        assert original_mem.documents == ["doc1"]


class TestMemoryStoreSave:
    """Tests for MemoryStore.save()."""

    def test_save_persists_all_roles(self):
        """Save should upsert a record for each role that has documents."""
        client = _make_mock_client()
        store = MemoryStore(client, max_entries=50)
        graph = FakeGraph()

        # Populate 3 of 5 roles
        graph.bull_memory.documents = ["doc1"]
        graph.bull_memory.recommendations = ["rec1"]
        graph.bear_memory.documents = ["doc2", "doc3"]
        graph.bear_memory.recommendations = ["rec2", "rec3"]
        graph.trader_memory.documents = ["doc4"]
        graph.trader_memory.recommendations = ["rec4"]

        total = store.save(graph)

        assert total == 4  # 1 + 2 + 1
        # Verify upsert was called 3 times (3 populated roles)
        assert client.table.return_value.upsert.call_count == 3

    def test_save_skips_empty_roles(self):
        """Roles with no documents should NOT be upserted."""
        client = _make_mock_client()
        store = MemoryStore(client, max_entries=50)
        graph = FakeGraph()

        # Only one role has data
        graph.bull_memory.documents = ["doc1"]
        graph.bull_memory.recommendations = ["rec1"]

        store.save(graph)

        assert client.table.return_value.upsert.call_count == 1

    def test_save_applies_fifo_cap(self):
        """When entries exceed max_entries, only the most recent are kept."""
        client = _make_mock_client()
        store = MemoryStore(client, max_entries=3)  # Cap at 3
        graph = FakeGraph()

        # Put 5 entries in bull_memory
        graph.bull_memory.documents = ["old1", "old2", "mid", "new1", "new2"]
        graph.bull_memory.recommendations = ["r_old1", "r_old2", "r_mid", "r_new1", "r_new2"]

        store.save(graph)

        # Verify the upsert was called with only the last 3 entries
        upsert_call = client.table.return_value.upsert.call_args
        upserted_data = upsert_call[0][0]  # First positional arg
        assert upserted_data["documents"] == ["mid", "new1", "new2"]
        assert upserted_data["recommendations"] == ["r_mid", "r_new1", "r_new2"]

    def test_save_no_cap_when_under_limit(self):
        """When entries are under max_entries, all are kept."""
        client = _make_mock_client()
        store = MemoryStore(client, max_entries=50)
        graph = FakeGraph()

        graph.bull_memory.documents = ["doc1", "doc2"]
        graph.bull_memory.recommendations = ["rec1", "rec2"]

        store.save(graph)

        upsert_call = client.table.return_value.upsert.call_args
        upserted_data = upsert_call[0][0]
        assert upserted_data["documents"] == ["doc1", "doc2"]

    def test_save_survives_upsert_error(self):
        """If one role's upsert fails, others should still be saved."""
        client = MagicMock()
        table = MagicMock()
        client.table.return_value = table

        call_count = 0

        def side_effect(data, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Supabase timeout")
            # Echo back the input data (valid for AgentMemoryRecord)
            chain = MagicMock()
            result = MagicMock()
            result.data = [data]
            chain.execute.return_value = result
            return chain

        table.upsert.side_effect = side_effect

        store = MemoryStore(client, max_entries=50)
        graph = FakeGraph()

        # Populate two roles — first will fail, second should succeed
        graph.bull_memory.documents = ["doc1"]
        graph.bull_memory.recommendations = ["rec1"]
        graph.bear_memory.documents = ["doc2"]
        graph.bear_memory.recommendations = ["rec2"]

        # Should not raise
        total = store.save(graph)
        # bull_memory failed (0), bear_memory succeeded (1)
        assert total == 1


class TestMemoryStoreRoundtrip:
    """Integration-style tests for save → load cycle."""

    def test_save_and_load_roundtrip(self):
        """Save memories, then load into a fresh graph — data should match."""
        # Phase 1: Save
        saved_data: dict[str, dict] = {}

        save_client = MagicMock()
        save_table = MagicMock()
        save_client.table.return_value = save_table

        def capture_upsert(data, **kwargs):
            saved_data[data["role"]] = data
            result = MagicMock()
            result.execute.return_value = MagicMock(data=[data])
            return result

        save_table.upsert.side_effect = capture_upsert

        save_store = MemoryStore(save_client, max_entries=50)
        save_graph = FakeGraph()
        save_graph.bull_memory.documents = ["lesson1", "lesson2"]
        save_graph.bull_memory.recommendations = ["rec1", "rec2"]
        save_graph.bear_memory.documents = ["warning1"]
        save_graph.bear_memory.recommendations = ["caution1"]

        save_store.save(save_graph)

        # Phase 2: Load into fresh graph using saved data
        rows = [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "user_id": None,
                "role": role_data["role"],
                "documents": role_data["documents"],
                "recommendations": role_data["recommendations"],
                "updated_at": "2025-06-01T00:00:00Z",
            }
            for role_data in saved_data.values()
        ]
        load_client = _make_mock_client(memory_rows=rows)
        load_store = MemoryStore(load_client, max_entries=50)
        load_graph = FakeGraph()

        total = load_store.load(load_graph)

        assert total == 3  # 2 + 1
        assert load_graph.bull_memory.documents == ["lesson1", "lesson2"]
        assert load_graph.bull_memory.recommendations == ["rec1", "rec2"]
        assert load_graph.bear_memory.documents == ["warning1"]
        assert load_graph.bear_memory.recommendations == ["caution1"]
        assert load_graph.bull_memory.index_rebuilt is True
        assert load_graph.bear_memory.index_rebuilt is True

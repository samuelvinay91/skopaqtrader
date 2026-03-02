"""Persistent agent memory backed by Supabase.

Serializes / deserializes the in-memory BM25 ``FinancialSituationMemory``
objects to a Supabase ``agent_memories`` table (one row per role, JSONB
arrays for documents and recommendations).

The BM25 index itself is NOT serialized — it is deterministically rebuilt
from the ``documents`` list on each load.

Design: operates on the **same** memory objects that the upstream
``TradingAgentsGraph`` holds as public attributes, so all agent node
closures continue to reference the correct instances.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from skopaq.db.models import AgentMemoryRecord
from skopaq.db.repositories import MemoryRepository

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)

# The 5 upstream memory attribute names on TradingAgentsGraph
MEMORY_ROLES = (
    "bull_memory",
    "bear_memory",
    "trader_memory",
    "invest_judge_memory",
    "risk_manager_memory",
)


class MemoryStore:
    """Load and save agent memories to Supabase.

    Args:
        client: Authenticated Supabase client (service-role key).
        max_entries: FIFO cap — oldest entries are pruned at save time.
    """

    def __init__(self, client: Client, max_entries: int = 50) -> None:
        self._repo = MemoryRepository(client)
        self._max_entries = max_entries

    def load(self, graph: Any) -> int:
        """Populate the graph's memory objects from Supabase.

        Mutates ``graph.<role>_memory.documents`` and
        ``graph.<role>_memory.recommendations`` **in place**, then
        rebuilds the BM25 index so agents can immediately query
        past lessons.

        Args:
            graph: An upstream ``TradingAgentsGraph`` instance.

        Returns:
            Total number of memory entries loaded across all roles.
        """
        total = 0
        try:
            records = self._repo.get_all_roles()
        except Exception:
            logger.warning("Failed to load agent memories from Supabase — starting fresh", exc_info=True)
            return 0

        # Index by role for O(1) lookup
        by_role: dict[str, AgentMemoryRecord] = {r.role: r for r in records}

        for role in MEMORY_ROLES:
            memory = getattr(graph, role, None)
            if memory is None:
                continue

            record = by_role.get(role)
            if record is None or not record.documents:
                continue

            # Validate parallel arrays
            docs = record.documents
            recs = record.recommendations
            if len(docs) != len(recs):
                logger.warning(
                    "Memory %s has mismatched lengths (docs=%d, recs=%d) — skipping",
                    role, len(docs), len(recs),
                )
                continue

            # Mutate in place (preserves upstream references)
            memory.documents = list(docs)
            memory.recommendations = list(recs)
            memory._rebuild_index()

            loaded = len(docs)
            total += loaded
            logger.info("Loaded %d memories for %s", loaded, role)

        logger.info("Total agent memories loaded: %d", total)
        return total

    def save(self, graph: Any) -> int:
        """Persist the graph's memory objects to Supabase.

        Applies a FIFO cap (``max_entries``) — only the most recent
        entries are kept.  Uses ``UPSERT`` on ``(user_id, role)``
        so each role has exactly one row.

        Args:
            graph: An upstream ``TradingAgentsGraph`` instance.

        Returns:
            Total number of memory entries saved across all roles.
        """
        total = 0

        for role in MEMORY_ROLES:
            memory = getattr(graph, role, None)
            if memory is None:
                continue

            docs = memory.documents
            recs = memory.recommendations

            if not docs:
                continue

            # FIFO cap — keep only the most recent entries
            if len(docs) > self._max_entries:
                docs = docs[-self._max_entries:]
                recs = recs[-self._max_entries:]

            record = AgentMemoryRecord(
                role=role,
                documents=docs,
                recommendations=recs,
            )

            try:
                self._repo.upsert(record)
                saved = len(docs)
                total += saved
                logger.info("Saved %d memories for %s", saved, role)
            except Exception:
                logger.warning("Failed to save memories for %s", role, exc_info=True)

        logger.info("Total agent memories saved: %d", total)
        return total

"""Data models for the scanner engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ScannerMetrics:
    """Computed metrics for a single symbol during a scan cycle."""

    symbol: str
    ltp: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    volume_ratio: float = 0.0  # Today's volume / avg volume
    gap_pct: float = 0.0       # Open vs prev close


@dataclass
class ScannerCandidate:
    """A stock identified by the scanner as worth full analysis."""

    symbol: str
    reason: str
    urgency: str = "normal"  # "high", "normal", "low"
    metrics: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "reason": self.reason,
            "urgency": self.urgency,
            "metrics": self.metrics,
            "timestamp": self.timestamp.isoformat(),
        }

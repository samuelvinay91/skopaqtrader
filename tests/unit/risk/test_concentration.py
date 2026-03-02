"""Tests for sector concentration checker.

Validates that the portfolio doesn't become over-exposed to a single sector,
using the static NIFTY 50 sector map.
"""

import pytest

from skopaq.broker.models import Exchange, Position, Product
from skopaq.risk.concentration import ConcentrationChecker, SECTOR_MAP, get_sector


# ── Helpers ───────────────────────────────────────────────────────────────────


def _position(symbol: str, qty: int = 10, price: float = 1000.0) -> Position:
    """Create a Position for testing."""
    return Position(
        symbol=symbol, exchange=Exchange.NSE, product=Product.CNC,
        quantity=qty, average_price=price, last_price=price,
        pnl=0, day_pnl=0,
    )


# ── Sector map tests ─────────────────────────────────────────────────────────


class TestSectorMap:
    def test_known_banking_stocks(self):
        assert get_sector("HDFCBANK") == "BANKING"
        assert get_sector("ICICIBANK") == "BANKING"
        assert get_sector("SBIN") == "BANKING"

    def test_known_it_stocks(self):
        assert get_sector("TCS") == "IT"
        assert get_sector("INFY") == "IT"
        assert get_sector("WIPRO") == "IT"

    def test_unknown_symbol_returns_other(self):
        assert get_sector("RANDOMSTOCK") == "OTHER"

    def test_case_insensitive(self):
        assert get_sector("reliance") == "OIL_GAS"
        assert get_sector("Reliance") == "OIL_GAS"

    def test_sector_map_coverage(self):
        """Ensure at least 40 NIFTY 50 stocks are mapped."""
        assert len(SECTOR_MAP) >= 40


# ── Concentration checker tests ───────────────────────────────────────────────


class TestConcentrationChecker:
    @pytest.fixture
    def checker(self):
        return ConcentrationChecker(max_sector_pct=0.40)

    def test_first_position_in_sector_passes(self, checker):
        """Single position in a sector with no existing holdings should pass."""
        result = checker.check(
            symbol="HDFCBANK",
            order_value=100_000,
            positions=[],
            portfolio_value=1_000_000,
        )
        assert result is None  # No rejection

    def test_within_limit_passes(self, checker):
        """30% existing + 5% new = 35% < 40% → passes."""
        positions = [
            _position("HDFCBANK", qty=100, price=1500),   # 150,000
            _position("ICICIBANK", qty=50, price=1000),    # 50,000
        ]
        # Existing banking = 200,000 out of 1,000,000 = 20%
        result = checker.check(
            symbol="SBIN",
            order_value=150_000,  # +15% = 35%
            positions=positions,
            portfolio_value=1_000_000,
        )
        assert result is None

    def test_exceeds_limit_rejected(self, checker):
        """35% existing + 10% new = 45% > 40% → rejected."""
        positions = [
            _position("HDFCBANK", qty=200, price=1500),  # 300,000 = 30%
            _position("SBIN", qty=50, price=1000),        # 50,000 = 5%
        ]
        # Existing banking = 350,000 = 35%
        result = checker.check(
            symbol="ICICIBANK",
            order_value=100_000,  # +10% = 45%
            positions=positions,
            portfolio_value=1_000_000,
        )
        assert result is not None
        assert "BANKING" in result
        assert "45%" in result

    def test_unknown_symbol_allowed(self, checker):
        """Symbols not in the sector map are always allowed."""
        result = checker.check(
            symbol="UNKNOWNSTOCK",
            order_value=500_000,  # 50% — would breach if mapped
            positions=[],
            portfolio_value=1_000_000,
        )
        assert result is None

    def test_different_sector_not_counted(self, checker):
        """Banking positions shouldn't affect IT sector check."""
        positions = [
            _position("HDFCBANK", qty=300, price=1500),  # 450,000 banking
        ]
        result = checker.check(
            symbol="TCS",          # IT sector
            order_value=300_000,   # 30% IT
            positions=positions,
            portfolio_value=1_000_000,
        )
        assert result is None

    def test_zero_portfolio_value_passes(self, checker):
        """Zero portfolio value should not crash or reject."""
        result = checker.check(
            symbol="HDFCBANK",
            order_value=100_000,
            positions=[],
            portfolio_value=0,
        )
        assert result is None

    def test_zero_quantity_positions_ignored(self, checker):
        """Closed positions (qty=0) should not count toward sector exposure."""
        positions = [
            _position("HDFCBANK", qty=0, price=1500),  # Closed
        ]
        result = checker.check(
            symbol="SBIN",
            order_value=400_000,  # 40% exactly
            positions=positions,
            portfolio_value=1_000_000,
        )
        assert result is None

    def test_exactly_at_limit_passes(self, checker):
        """Concentration of exactly 40% should pass (> not >=)."""
        result = checker.check(
            symbol="HDFCBANK",
            order_value=400_000,  # Exactly 40%
            positions=[],
            portfolio_value=1_000_000,
        )
        assert result is None

    def test_strict_limit(self):
        """Custom lower limit (20%) should reject at lower threshold."""
        checker = ConcentrationChecker(max_sector_pct=0.20)
        result = checker.check(
            symbol="HDFCBANK",
            order_value=250_000,  # 25% > 20%
            positions=[],
            portfolio_value=1_000_000,
        )
        assert result is not None

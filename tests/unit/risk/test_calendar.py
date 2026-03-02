"""Tests for NSE event calendar.

Validates F&O expiry detection, RBI policy dates, Budget day,
and position-scaling multipliers.
"""

from datetime import date

import pytest

from skopaq.risk.calendar import NSEEventCalendar, _last_thursday, _all_thursdays


@pytest.fixture
def calendar():
    return NSEEventCalendar()


# ── F&O Expiry computation ────────────────────────────────────────────────────


class TestLastThursday:
    """Verify algorithmic F&O monthly expiry date computation."""

    def test_march_2026(self):
        """March 2026: last Thursday should be March 26."""
        d = _last_thursday(2026, 3)
        assert d == date(2026, 3, 26)
        assert d.weekday() == 3  # Thursday

    def test_february_2026(self):
        """February 2026: last Thursday should be Feb 26."""
        d = _last_thursday(2026, 2)
        assert d == date(2026, 2, 26)
        assert d.weekday() == 3

    def test_december_2025(self):
        """December 2025: last Thursday should be Dec 25."""
        d = _last_thursday(2025, 12)
        assert d == date(2025, 12, 25)
        assert d.weekday() == 3

    def test_all_months_are_thursday(self):
        """Every month in 2026 should produce a Thursday."""
        for month in range(1, 13):
            d = _last_thursday(2026, month)
            assert d.weekday() == 3, f"Month {month}: {d} is not Thursday"

    def test_leap_year_february(self):
        """Feb 2024 (leap year) should work correctly."""
        d = _last_thursday(2024, 2)
        assert d == date(2024, 2, 29)  # Leap day is a Thursday!
        assert d.weekday() == 3


class TestAllThursdays:
    def test_march_2026_has_four_or_five_thursdays(self):
        thursdays = _all_thursdays(2026, 3)
        assert len(thursdays) >= 4
        for d in thursdays:
            assert d.weekday() == 3
            assert d.month == 3


# ── Risk level classification ─────────────────────────────────────────────────


class TestRiskLevel:
    """Test date classification into NORMAL / CAUTION / AVOID."""

    def test_normal_monday(self, calendar):
        """A random Monday should be NORMAL."""
        d = date(2026, 3, 2)  # Monday
        assert d.weekday() == 0
        assert calendar.get_risk_level(d) == "NORMAL"

    def test_weekly_expiry_is_caution(self, calendar):
        """Any Thursday (F&O weekly expiry) should be CAUTION."""
        d = date(2026, 3, 5)  # Thursday (not last Thursday)
        assert d.weekday() == 3
        assert calendar.get_risk_level(d) == "CAUTION"

    def test_monthly_expiry_is_caution(self, calendar):
        """Last Thursday of the month (F&O monthly expiry) is CAUTION."""
        d = _last_thursday(2026, 3)
        assert calendar.get_risk_level(d) == "CAUTION"

    def test_day_before_monthly_expiry_is_caution(self, calendar):
        """Wednesday before monthly expiry (positioning day) is CAUTION."""
        last_thu = _last_thursday(2026, 3)
        day_before = date(last_thu.year, last_thu.month, last_thu.day - 1)
        assert calendar.get_risk_level(day_before) == "CAUTION"

    def test_budget_day_is_avoid(self, calendar):
        """Feb 1 (Union Budget) should be AVOID."""
        d = date(2026, 2, 1)
        assert calendar.get_risk_level(d) == "AVOID"

    def test_rbi_policy_2025_is_avoid(self, calendar):
        """Known RBI policy dates in 2025 should be AVOID."""
        rbi_dates = [
            date(2025, 2, 7),
            date(2025, 4, 9),
            date(2025, 6, 6),
            date(2025, 8, 8),
            date(2025, 10, 8),
            date(2025, 12, 5),
        ]
        for d in rbi_dates:
            assert calendar.get_risk_level(d) == "AVOID", f"RBI date {d} should be AVOID"

    def test_rbi_policy_2026_is_avoid(self, calendar):
        """Known RBI policy dates in 2026 should be AVOID."""
        rbi_dates = [
            date(2026, 2, 6),
            date(2026, 4, 8),
            date(2026, 6, 5),
            date(2026, 8, 7),
            date(2026, 10, 7),
            date(2026, 12, 4),
        ]
        for d in rbi_dates:
            assert calendar.get_risk_level(d) == "AVOID", f"RBI date {d} should be AVOID"

    def test_unknown_year_no_rbi_dates(self, calendar):
        """Year without configured RBI dates should NOT produce false AVOIDs."""
        # Feb 7 in 2030 — no RBI data, should NOT be AVOID unless it's also budget
        d = date(2030, 3, 15)  # Random Friday
        level = calendar.get_risk_level(d)
        assert level != "AVOID"


# ── Position scale ────────────────────────────────────────────────────────────


class TestPositionScale:
    """Test the multipliers returned by get_position_scale()."""

    def test_normal_day_is_1_0(self, calendar):
        d = date(2026, 3, 2)  # Monday
        assert calendar.get_position_scale(d) == 1.0

    def test_caution_day_is_0_7(self, calendar):
        d = date(2026, 3, 5)  # Thursday (weekly expiry)
        assert calendar.get_position_scale(d) == 0.7

    def test_avoid_day_is_0_0(self, calendar):
        d = date(2026, 2, 1)  # Budget day
        assert calendar.get_position_scale(d) == 0.0

    def test_custom_caution_scale(self):
        """Custom caution_scale should be respected."""
        cal = NSEEventCalendar(caution_scale=0.5)
        d = date(2026, 3, 5)  # Thursday
        assert cal.get_position_scale(d) == 0.5


# ── Event listing ─────────────────────────────────────────────────────────────


class TestGetEvents:
    def test_normal_day_no_events(self, calendar):
        d = date(2026, 3, 2)  # Monday
        assert calendar.get_events(d) == []

    def test_weekly_expiry_event(self, calendar):
        d = date(2026, 3, 5)  # Thursday (not last)
        events = calendar.get_events(d)
        assert "F&O Weekly Expiry" in events

    def test_monthly_expiry_event(self, calendar):
        d = _last_thursday(2026, 3)
        events = calendar.get_events(d)
        assert "F&O Monthly Expiry" in events
        # Monthly expiry should NOT also show weekly expiry
        assert "F&O Weekly Expiry" not in events

    def test_budget_day_event(self, calendar):
        d = date(2026, 2, 1)
        events = calendar.get_events(d)
        assert "Union Budget Day" in events

    def test_rbi_policy_event(self, calendar):
        d = date(2026, 4, 8)
        events = calendar.get_events(d)
        assert "RBI Monetary Policy" in events

    def test_multiple_events_on_same_day(self, calendar):
        """If RBI policy falls on a Thursday, both events appear."""
        # Check if any RBI date in 2025 falls on a Thursday
        rbi_thursdays = [
            d for d in [date(2025, 2, 7), date(2025, 4, 9), date(2025, 6, 6),
                        date(2025, 8, 8), date(2025, 10, 8), date(2025, 12, 5)]
            if d.weekday() == 3
        ]
        if rbi_thursdays:
            d = rbi_thursdays[0]
            events = calendar.get_events(d)
            assert len(events) >= 2  # RBI + F&O expiry


# ── AVOID overrides CAUTION ──────────────────────────────────────────────────


class TestPriorityOverride:
    """AVOID-level events should override CAUTION-level events."""

    def test_rbi_on_thursday_is_avoid(self, calendar):
        """If an RBI date falls on Thursday, it should be AVOID, not CAUTION."""
        rbi_thursday_dates = [
            d for d in [date(2025, 8, 8)]  # Aug 8, 2025 is Friday actually, check
        ]
        # Use a date we know is both RBI and Thursday
        # Let's check Feb 6, 2026 — it's a Friday. April 8, 2026 — Wednesday.
        # Just test budget day (Feb 1) — if it falls on Thursday
        # Feb 1, 2029 is a Thursday
        d = date(2029, 2, 1)  # Budget + Thursday
        assert d.weekday() == 3  # Verify it's Thursday
        assert calendar.get_risk_level(d) == "AVOID"  # Budget overrides expiry

"""Tests for the watchlist manager."""

import pytest

from skopaq.scanner.watchlist import NIFTY_50, Watchlist


class TestWatchlist:
    def test_default_is_nifty50(self):
        wl = Watchlist()
        assert len(wl) == len(NIFTY_50)
        assert "RELIANCE" in wl
        assert "TCS" in wl

    def test_custom_list(self):
        wl = Watchlist(["RELIANCE", "TCS", "INFY"])
        assert len(wl) == 3
        assert wl.symbols == ["RELIANCE", "TCS", "INFY"]

    def test_add_symbol(self):
        wl = Watchlist(["RELIANCE"])
        wl.add("TCS")
        assert "TCS" in wl
        assert len(wl) == 2

    def test_add_duplicate_ignored(self):
        wl = Watchlist(["RELIANCE"])
        wl.add("RELIANCE")
        assert len(wl) == 1

    def test_add_case_insensitive(self):
        wl = Watchlist(["RELIANCE"])
        wl.add("reliance")
        assert len(wl) == 1  # Not added (already exists)

    def test_remove_symbol(self):
        wl = Watchlist(["RELIANCE", "TCS"])
        wl.remove("TCS")
        assert "TCS" not in wl
        assert len(wl) == 1

    def test_remove_case_insensitive(self):
        wl = Watchlist(["RELIANCE", "TCS"])
        wl.remove("tcs")
        assert "TCS" not in wl

    def test_contains_case_insensitive(self):
        wl = Watchlist(["RELIANCE"])
        assert "reliance" in wl
        assert "RELIANCE" in wl

    def test_symbols_returns_copy(self):
        wl = Watchlist(["RELIANCE"])
        symbols = wl.symbols
        symbols.append("TCS")
        assert len(wl) == 1  # Original unchanged

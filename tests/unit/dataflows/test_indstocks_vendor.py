"""Tests for the INDstocks data vendor integration."""

import pytest

from tradingagents.dataflows.interface import VENDOR_LIST, VENDOR_METHODS


class TestVendorRegistration:
    def test_indstocks_in_vendor_list(self):
        assert "indstocks" in VENDOR_LIST

    def test_indstocks_is_first_vendor(self):
        assert VENDOR_LIST[0] == "indstocks"

    def test_indstocks_registered_for_stock_data(self):
        assert "indstocks" in VENDOR_METHODS["get_stock_data"]

    def test_indstocks_function_is_callable(self):
        func = VENDOR_METHODS["get_stock_data"]["indstocks"]
        assert callable(func)

    def test_indstocks_function_has_correct_name(self):
        func = VENDOR_METHODS["get_stock_data"]["indstocks"]
        assert func.__name__ == "get_stock_data_indstocks"


class TestRunAsync:
    """Test the async-to-sync bridge utility."""

    def test_run_async_executes_coroutine(self):
        from tradingagents.dataflows.indstocks import _run_async

        async def simple_coro():
            return 42

        result = _run_async(simple_coro())
        assert result == 42

    def test_run_async_propagates_exception(self):
        from tradingagents.dataflows.indstocks import _run_async

        async def failing_coro():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            _run_async(failing_coro())

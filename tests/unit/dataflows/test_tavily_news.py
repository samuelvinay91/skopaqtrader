"""Tests for the Tavily news data vendor integration."""

import sys
import pytest
from unittest.mock import patch, MagicMock

# Ensure the tavily module is mockable even when not installed in the venv.
_mock_tavily_module = MagicMock()
if "tavily" not in sys.modules:
    sys.modules["tavily"] = _mock_tavily_module


class TestGetTavilyClient:
    """Tests for _get_tavily_client()."""

    @patch("tavily.TavilyClient")
    @patch.dict("os.environ", {}, clear=True)
    def test_raises_when_api_key_missing(self, _mock_client_cls):
        from tradingagents.dataflows.tavily_news import _get_tavily_client

        with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
            _get_tavily_client()

    @patch("tavily.TavilyClient")
    @patch.dict("os.environ", {"TAVILY_API_KEY": "tvly-test-key"})
    def test_returns_client_when_key_present(self, mock_client_cls):
        from tradingagents.dataflows.tavily_news import _get_tavily_client

        client = _get_tavily_client()
        mock_client_cls.assert_called_once_with(api_key="tvly-test-key")
        assert client is mock_client_cls.return_value


class TestGetNewsTavily:
    """Tests for get_news_tavily()."""

    @patch("tradingagents.dataflows.tavily_news._get_tavily_client")
    def test_returns_formatted_string_on_success(self, mock_get_client):
        from tradingagents.dataflows.tavily_news import get_news_tavily

        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "AAPL hits record high",
                    "content": "Apple shares surged today.",
                    "url": "https://example.com/aapl",
                },
                {
                    "title": "Tech rally continues",
                    "content": "Markets are up.",
                    "url": "https://example.com/tech",
                },
            ]
        }
        mock_get_client.return_value = mock_client

        result = get_news_tavily("AAPL", "2025-01-01", "2025-01-07")

        assert "AAPL News" in result
        assert "2025-01-01" in result
        assert "2025-01-07" in result
        assert "AAPL hits record high" in result
        assert "Apple shares surged today." in result
        assert "https://example.com/aapl" in result
        assert "Tech rally continues" in result

        mock_client.search.assert_called_once_with(
            query="AAPL stock news",
            max_results=10,
            search_depth="basic",
            topic="news",
        )

    @patch("tradingagents.dataflows.tavily_news._get_tavily_client")
    def test_returns_no_news_when_empty_results(self, mock_get_client):
        from tradingagents.dataflows.tavily_news import get_news_tavily

        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        mock_get_client.return_value = mock_client

        result = get_news_tavily("AAPL", "2025-01-01", "2025-01-07")
        assert result == "No news found for AAPL"

    @patch("tradingagents.dataflows.tavily_news._get_tavily_client")
    def test_returns_error_string_on_exception(self, mock_get_client):
        from tradingagents.dataflows.tavily_news import get_news_tavily

        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("API quota exceeded")
        mock_get_client.return_value = mock_client

        result = get_news_tavily("AAPL", "2025-01-01", "2025-01-07")
        assert "Error fetching news for AAPL" in result
        assert "API quota exceeded" in result


class TestGetGlobalNewsTavily:
    """Tests for get_global_news_tavily()."""

    @patch("tradingagents.dataflows.tavily_news._get_tavily_client")
    def test_returns_formatted_string_on_success(self, mock_get_client):
        from tradingagents.dataflows.tavily_news import get_global_news_tavily

        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "Fed holds rates steady",
                    "content": "The Federal Reserve announced no change.",
                    "url": "https://example.com/fed",
                },
            ]
        }
        mock_get_client.return_value = mock_client

        result = get_global_news_tavily("2025-01-07", look_back_days=7, limit=5)

        assert "Global Market News" in result
        assert "2025-01-07" in result
        assert "2024-12-31" in result
        assert "Fed holds rates steady" in result
        assert "The Federal Reserve announced no change." in result
        assert "https://example.com/fed" in result

        mock_client.search.assert_called_once_with(
            query="global stock market economy financial news",
            max_results=5,
            search_depth="basic",
            topic="news",
        )

    @patch("tradingagents.dataflows.tavily_news._get_tavily_client")
    def test_returns_no_news_when_empty_results(self, mock_get_client):
        from tradingagents.dataflows.tavily_news import get_global_news_tavily

        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        mock_get_client.return_value = mock_client

        result = get_global_news_tavily("2025-01-07")
        assert result == "No global news found for 2025-01-07"

    @patch("tradingagents.dataflows.tavily_news._get_tavily_client")
    def test_returns_error_string_on_exception(self, mock_get_client):
        from tradingagents.dataflows.tavily_news import get_global_news_tavily

        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("Network timeout")
        mock_get_client.return_value = mock_client

        result = get_global_news_tavily("2025-01-07")
        assert "Error fetching global news" in result
        assert "Network timeout" in result


try:
    from tradingagents.dataflows.interface import VENDOR_LIST, VENDOR_METHODS
    _has_interface_deps = True
except ImportError:
    _has_interface_deps = False


@pytest.mark.skipif(not _has_interface_deps, reason="interface dependencies not installed")
class TestTavilyVendorRegistration:
    """Tests for Tavily registration in the vendor interface."""

    def test_tavily_in_vendor_list(self):
        assert "tavily" in VENDOR_LIST

    def test_tavily_registered_for_get_news(self):
        assert "tavily" in VENDOR_METHODS["get_news"]
        assert callable(VENDOR_METHODS["get_news"]["tavily"])

    def test_tavily_registered_for_get_global_news(self):
        assert "tavily" in VENDOR_METHODS["get_global_news"]
        assert callable(VENDOR_METHODS["get_global_news"]["tavily"])

    def test_tavily_news_function_names(self):
        assert VENDOR_METHODS["get_news"]["tavily"].__name__ == "get_news_tavily"
        assert VENDOR_METHODS["get_global_news"]["tavily"].__name__ == "get_global_news_tavily"

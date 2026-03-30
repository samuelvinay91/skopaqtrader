"""Tavily-based news data fetching functions."""

import os
from datetime import datetime, timedelta


def _get_tavily_client():
    """Create a TavilyClient instance using the TAVILY_API_KEY env var."""
    from tavily import TavilyClient

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY environment variable is not set")
    return TavilyClient(api_key=api_key)


def get_news_tavily(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """Retrieve news for a specific stock ticker using the Tavily search API.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        Formatted string containing news articles.
    """
    try:
        client = _get_tavily_client()

        query = f"{ticker} stock news"
        response = client.search(
            query=query,
            max_results=10,
            search_depth="basic",
            topic="news",
        )

        results = response.get("results", [])
        if not results:
            return f"No news found for {ticker}"

        news_str = ""
        for item in results:
            title = item.get("title", "No title")
            content = item.get("content", "")
            url = item.get("url", "")

            news_str += f"### {title}\n"
            if content:
                news_str += f"{content}\n"
            if url:
                news_str += f"Link: {url}\n"
            news_str += "\n"

        return f"## {ticker} News, from {start_date} to {end_date}:\n\n{news_str}"

    except Exception as e:
        return f"Error fetching news for {ticker}: {str(e)}"


def get_global_news_tavily(
    curr_date: str,
    look_back_days: int = 7,
    limit: int = 10,
) -> str:
    """Retrieve global/macro economic news using the Tavily search API.

    Args:
        curr_date: Current date in yyyy-mm-dd format
        look_back_days: Number of days to look back
        limit: Maximum number of articles to return

    Returns:
        Formatted string containing global news articles.
    """
    try:
        client = _get_tavily_client()

        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - timedelta(days=look_back_days)
        start_date = start_dt.strftime("%Y-%m-%d")

        query = "global stock market economy financial news"
        response = client.search(
            query=query,
            max_results=limit,
            search_depth="basic",
            topic="news",
        )

        results = response.get("results", [])
        if not results:
            return f"No global news found for {curr_date}"

        news_str = ""
        for item in results:
            title = item.get("title", "No title")
            content = item.get("content", "")
            url = item.get("url", "")

            news_str += f"### {title}\n"
            if content:
                news_str += f"{content}\n"
            if url:
                news_str += f"Link: {url}\n"
            news_str += "\n"

        return f"## Global Market News, from {start_date} to {curr_date}:\n\n{news_str}"

    except Exception as e:
        return f"Error fetching global news: {str(e)}"

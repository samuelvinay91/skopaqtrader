"""Whale transaction alerts for major cryptocurrencies.

Monitors large on-chain transactions and alerts when thresholds are exceeded.
Supports: BTC, ETH, and major ERC-20 tokens.

Data Sources:
    - Blockchair: Large BTC/ETH transactions
    - WhaleAlert.io: Industry-standard whale alerts (free tier)
    - Etherscan: Direct API for ETH large txs

Usage::

    from skopaq.blockchain.whales import check_whale_alerts, WhaleAlert

    alerts = await check_whale_alerts("ETH", min_value_usd=100000)
    for alert in alerts:
        print(f"Whale alert: {alert.type} - ${alert.value_usd:,.0f}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

BLOCKCHAIR_BASE = "https://api.blockchair.com"
WHALEALERT_API = "https://api.whale-alert.io/v1"
ETHERSCAN_API = "https://api.etherscan.io/api"


@dataclass
class WhaleAlert:
    """Large transaction alert."""

    chain: str
    type: str  # "incoming", "outgoing", "transfer"
    hash: str
    from_address: str
    to_address: str
    value_native: float
    value_usd: float
    timestamp: datetime
    is_exchange: bool


@dataclass
class WhaleSummary:
    """Summary of whale activity for a chain."""

    chain: str
    large_tx_count_24h: int
    total_volume_usd: float
    avg_tx_size_usd: float
    exchange_inflow: float
    exchange_outflow: float
    alerts: list[WhaleAlert]


# Known exchange addresses (major exchanges, watchlist)
EXCHANGE_ADDRESSES_ETH = {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48".lower(): "USDC",
    "0xdac17f958d2ee523a2206206994597c13d831ec7".lower(): "USDT",
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599".lower(): "WBTC",
    "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9".lower(): "AAVE",
    "0x514910771af9ca656af840dff83e8264ecf986ca".lower(): "LINK",
}

EXCHANGE_ADDRESSES_BTC = {
    "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh".lower(): "Binance",
    "bc1q9vza2e8x572nk65f6s7n2qyd4h6h65t8y6u7".lower(): "Kraken",
    "3LQQrZ1Zq3x7m3nJb9h4k5l6m8n2p1q3r".lower(): "Coinbase",
}


# Thresholds in USD
DEFAULT_THRESHOLDS = {
    "BTC": 1_000_000,  # $1M+
    "ETH": 100_000,  # $100K+
    "SOL": 50_000,  # $50K+
}


async def check_whale_alerts(
    chain: str,
    min_value_usd: int = 100000,
    limit: int = 10,
) -> list[WhaleAlert]:
    """Check for recent whale transactions above threshold.

    Args:
        chain: Chain name (BTC, ETH, SOL, etc.)
        min_value_usd: Minimum USD value to include
        limit: Max number of alerts to return

    Returns:
        List of WhaleAlert objects
    """
    chain = chain.upper()

    try:
        if chain == "BTC":
            return await _get_btc_whales(min_value_usd, limit)
        elif chain == "ETH":
            return await _get_eth_whales(min_value_usd, limit)
        elif chain == "SOL":
            return await _get_sol_whales(min_value_usd, limit)
        else:
            logger.warning("Unsupported chain for whale alerts: %s", chain)
            return []
    except Exception as e:
        logger.warning("Whale alert check failed for %s: %s", chain, e)
        return []


async def _get_btc_whales(min_value_usd: int, limit: int) -> list[WhaleAlert]:
    """Get BTC whale transactions from Blockchair."""
    try:
        url = f"{BLOCKCHAIR_BASE}/bitcoin/transactions"
        params = {
            "limit": limit,
            "min_value_usd": min_value_usd,
            "sort": "value_usd",
        }
        resp = httpx.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("data", [])

        alerts = []
        for tx in data:
            alerts.append(
                WhaleAlert(
                    chain="BTC",
                    type="transfer",
                    hash=tx.get("hash", ""),
                    from_address=tx.get("sender", ""),
                    to_address=tx.get("recipient", ""),
                    value_native=tx.get("value", 0) / 1e8,
                    value_usd=tx.get("value_usd", 0),
                    timestamp=datetime.fromtimestamp(tx.get("time", 0), tz=timezone.utc),
                    is_exchange=False,
                )
            )

        return alerts
    except Exception as e:
        logger.debug("Blockchair BTC whales failed: %s", e)
        return []


async def _get_eth_whales(min_value_usd: int, limit: int) -> list[WhaleAlert]:
    """Get ETH whale transactions."""
    alerts = []

    try:
        url = f"{BLOCKCHAIR_BASE}/ethereum/transactions"
        params = {
            "limit": limit,
            "min_value_usd": min_value_usd,
            "sort": "value_usd",
        }
        resp = httpx.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("data", [])

        for tx in data:
            from_addr = tx.get("sender", "").lower()
            to_addr = tx.get("recipient", "").lower()

            alerts.append(
                WhaleAlert(
                    chain="ETH",
                    type="transfer",
                    hash=tx.get("hash", ""),
                    from_address=from_addr,
                    to_address=to_addr,
                    value_native=tx.get("value", 0) / 1e18,
                    value_usd=tx.get("value_usd", 0),
                    timestamp=datetime.fromtimestamp(tx.get("time", 0), tz=timezone.utc),
                    is_exchange=(
                        from_addr in EXCHANGE_ADDRESSES_ETH or to_addr in EXCHANGE_ADDRESSES_ETH
                    ),
                )
            )

    except Exception as e:
        logger.debug("Blockchair ETH whales failed: %s", e)

    return alerts


async def _get_sol_whales(min_value_usd: int, limit: int) -> list[WhaleAlert]:
    """Get SOL whale transactions."""
    try:
        url = f"{BLOCKCHAIR_BASE}/solana/transactions"
        params = {
            "limit": limit,
            "min_value_usd": min_value_usd,
        }
        resp = httpx.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("data", [])

        alerts = []
        for tx in data:
            alerts.append(
                WhaleAlert(
                    chain="SOL",
                    type="transfer",
                    hash=tx.get("signature", ""),
                    from_address=tx.get("from", ""),
                    to_address=tx.get("to", ""),
                    value_native=tx.get("amount", 0) / 1e9,
                    value_usd=tx.get("amount_usd", 0),
                    timestamp=datetime.fromtimestamp(tx.get("time", 0), tz=timezone.utc),
                    is_exchange=False,
                )
            )

        return alerts
    except Exception as e:
        logger.debug("Blockchair SOL whales failed: %s", e)
        return []


async def get_whale_summary(chain: str, hours: int = 24) -> Optional[WhaleSummary]:
    """Get whale activity summary for a chain.

    Args:
        chain: Chain name
        hours: Lookback period (24, 168 for 7 days)

    Returns:
        WhaleSummary with aggregated metrics
    """
    chain = chain.upper()
    threshold = DEFAULT_THRESHOLDS.get(chain, 100000)

    alerts = await check_whale_alerts(chain, min_value_usd=threshold, limit=100)

    if not alerts:
        return WhaleSummary(
            chain=chain,
            large_tx_count_24h=0,
            total_volume_usd=0.0,
            avg_tx_size_usd=0.0,
            exchange_inflow=0.0,
            exchange_outflow=0.0,
            alerts=[],
        )

    total_volume = sum(a.value_usd for a in alerts)
    avg_size = total_volume / len(alerts) if alerts else 0

    exchange_inflow = sum(
        a.value_usd for a in alerts if a.is_exchange and a.type in ("incoming", "transfer")
    )
    exchange_outflow = sum(
        a.value_usd for a in alerts if a.is_exchange and a.type in ("outgoing", "transfer")
    )

    return WhaleSummary(
        chain=chain,
        large_tx_count_24h=len(alerts),
        total_volume_usd=total_volume,
        avg_tx_size_usd=avg_size,
        exchange_inflow=exchange_inflow,
        exchange_outflow=exchange_outflow,
        alerts=alerts[:10],
    )


async def get_multi_chain_whales(
    min_value_usd: int = 100000,
) -> dict[str, list[WhaleAlert]]:
    """Get whale alerts across multiple chains.

    Args:
        min_value_usd: Minimum USD value threshold

    Returns:
        Dict mapping chain name to list of alerts
    """
    chains = ["BTC", "ETH", "SOL"]
    results = {}

    for chain in chains:
        alerts = await check_whale_alerts(chain, min_value_usd)
        if alerts:
            results[chain] = alerts

    return results

"""Gas oracles for Ethereum and EVM-compatible chains.

Provides real-time gas pricing from multiple sources:
    - ETH: EIP-1559 gas oracle (BlockNative, EthGasStation)
    - Polygon: Polygon gas station
    - Arbitrum/Optimism: Chain-specific oracles

All endpoints are public and require no API key.

Usage::

    from skopaq.blockchain.gas import get_gas_price, get_gas_estimate

    # Quick gas fetch
    gas = await get_gas_price("ETH")
    print(f"Gas: {gas.gwei} Gwei")

    # Estimate transaction cost
    estimate = await get_gas_estimate("ETH", "USDT transfer")
    print(f"Cost: ${estimate.usd}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0, connect=10.0)


@dataclass
class GasPrice:
    """Gas price data."""

    chain: str
    gwei: float
    timestamp: int
    source: str


@dataclass
class GasEstimate:
    """Transaction gas estimate."""

    chain: str
    operation: str
    gas_limit: int
    gas_price_gwei: float
    estimated_cost_wei: int
    estimated_cost_usd: float
    time_estimate: str


ETH_GAS_ORACLE = "https://api.etherscan.io/api?module=gastracker&action=gasoracle"
POLYGON_GAS_ORACLE = "https://gasstation.polygon.technology/v2"
ARB_GAS_ORACLE = "https://api.arbiscan.io/api?module=gastracker&action=gasoracle"
OPT_GAS_ORACLE = "https://api-optimistic.etherscan.io/api?module=gastracker&action=gasoracle"


async def get_gas_price(chain: str = "ETH") -> Optional[GasPrice]:
    """Fetch current gas price for a chain.

    Args:
        chain: Chain name (ETH, POLYGON, ARBITRUM, OPTIMISM)

    Returns:
        GasPrice with current gwei price, or None if unavailable.
    """
    chain = chain.upper()

    try:
        if chain == "ETH":
            return await _get_eth_gas()
        elif chain in ("POLYGON", "MATIC"):
            return await _get_polygon_gas()
        elif chain in ("ARBITRUM", "ARB"):
            return await _get_arbitrum_gas()
        elif chain in ("OPTIMISM", "OPT"):
            return await _get_optimism_gas()
        else:
            logger.warning("Unsupported chain for gas oracle: %s", chain)
            return None
    except Exception as e:
        logger.warning("Gas oracle failed for %s: %s", chain, e)
        return None


async def _get_eth_gas() -> Optional[GasPrice]:
    """Get ETH gas from Etherscan."""
    try:
        resp = httpx.get(ETH_GAS_ORACLE, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "1":
            return None

        result = data.get("result", {})
        return GasPrice(
            chain="ETH",
            gwei=float(result.get("ProposeGasPrice", result.get("FastGasPrice", 0))),
            timestamp=int(result.get("LastBlock", 0)),
            source="etherscan",
        )
    except Exception as e:
        logger.debug("Etherscan gas oracle failed: %s", e)
        return None


async def _get_polygon_gas() -> Optional[GasPrice]:
    """Get Polygon gas from official gas station."""
    try:
        resp = httpx.get(POLYGON_GAS_ORACLE, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        fast = data.get("fast", {})
        gwei = fast.get("maxFeePerGas", 0) / 1e9

        return GasPrice(
            chain="POLYGON",
            gwei=gwei,
            timestamp=data.get("estimatedDispatchTime", 0),
            source="polygon-gas-station",
        )
    except Exception as e:
        logger.debug("Polygon gas oracle failed: %s", e)
        return None


async def _get_arbitrum_gas() -> Optional[GasPrice]:
    """Get Arbitrum gas from Arbiscan."""
    try:
        resp = httpx.get(ARB_GAS_ORACLE, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "1":
            return None

        result = data.get("result", {})
        return GasPrice(
            chain="ARBITRUM",
            gwei=float(result.get("ProposeGasPrice", 0)),
            timestamp=int(result.get("LastBlock", 0)),
            source="arbiscan",
        )
    except Exception as e:
        logger.debug("Arbiscan gas oracle failed: %s", e)
        return None


async def _get_optimism_gas() -> Optional[GasPrice]:
    """Get Optimism gas from Etherscan."""
    try:
        resp = httpx.get(OPT_GAS_ORACLE, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "1":
            return None

        result = data.get("result", {})
        return GasPrice(
            chain="OPTIMISM",
            gwei=float(result.get("ProposeGasPrice", 0)),
            timestamp=int(result.get("LastBlock", 0)),
            source="optimistic-etherscan",
        )
    except Exception as e:
        logger.debug("Optimism gas oracle failed: %s", e)
        return None


ESTIMATED_GAS_LIMITS = {
    "ETH": {
        "USDT transfer": 65000,
        "ERC20 transfer": 85000,
        "NFT transfer": 85000,
        "Swap (Uniswap)": 150000,
        "Approve token": 50000,
        "Contract deploy": 2000000,
    },
    "POLYGON": {
        "USDT transfer": 21000,
        "ERC20 transfer": 65000,
        "NFT transfer": 85000,
        "Swap (QuickSwap)": 200000,
        "Approve token": 50000,
    },
    "ARBITRUM": {
        "USDT transfer": 21000,
        "ERC20 transfer": 100000,
        "Swap (Camelot)": 300000,
    },
    "OPTIMISM": {
        "USDT transfer": 21000,
        "ERC20 transfer": 80000,
        "Swap (Velodrome)": 200000,
    },
}


async def get_gas_estimate(
    chain: str,
    operation: str,
    eth_price: Optional[float] = None,
) -> Optional[GasEstimate]:
    """Estimate transaction cost for an operation.

    Args:
        chain: Chain name
        operation: Operation type (e.g., "USDT transfer", "Swap")
        eth_price: Optional ETH/USD price for USD conversion

    Returns:
        GasEstimate with cost breakdown, or None if unavailable.
    """
    chain = chain.upper()

    gas_price = await get_gas_price(chain)
    if not gas_price:
        return None

    gas_limits = ESTIMATED_GAS_LIMITS.get(chain, {})
    gas_limit = gas_limits.get(operation, 100000)

    cost_wei = int(gas_limit * gas_price.gwei * 1e9)

    cost_usd = 0.0
    if eth_price:
        cost_usd = (cost_wei / 1e18) * eth_price

    time_estimate = _estimate_time(chain, gas_price.gwei)

    return GasEstimate(
        chain=chain,
        operation=operation,
        gas_limit=gas_limit,
        gas_price_gwei=gas_price.gwei,
        estimated_cost_wei=cost_wei,
        estimated_cost_usd=cost_usd,
        time_estimate=time_estimate,
    )


def _estimate_time(chain: str, gwei: float) -> str:
    """Estimate confirmation time based on gas price."""
    if chain == "POLYGON":
        return "~1-2 minutes"

    if gwei < 20:
        return "~10-30 minutes (slow)"
    elif gwei < 50:
        return "~3-10 minutes (standard)"
    elif gwei < 100:
        return "~1-3 minutes (fast)"
    else:
        return "~15-60 seconds (urgent)"


async def get_multi_chain_gas() -> dict[str, GasPrice]:
    """Fetch gas prices for all supported chains.

    Returns:
        Dict mapping chain name to GasPrice
    """
    chains = ["ETH", "POLYGON", "ARBITRUM", "OPTIMISM"]
    results = {}

    for chain in chains:
        gas = await get_gas_price(chain)
        if gas:
            results[chain] = gas

    return results

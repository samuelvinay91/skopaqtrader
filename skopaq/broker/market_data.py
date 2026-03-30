"""Market data provider with automatic source fallback.

Provides a unified async interface for fetching quotes and LTP from
multiple sources.  The provider tries each source in priority order:

    1. **Broker API** (INDstocks or Kite Connect) — best data, real bid/ask/depth
    2. **yfinance** (no credentials) — free, covers NSE/BSE/crypto
    3. **Cached quote** — returns last known quote if all sources fail

This allows paper trading to work without any broker credentials while
still using live broker data when available.

Usage::

    provider = MarketDataProvider(config)
    provider.set_broker_client(client)   # optional — enhances data quality
    quote = await provider.get_quote("RELIANCE")
    ltp = await provider.get_ltp("RELIANCE")
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional, Protocol

from skopaq.broker.models import Quote

if TYPE_CHECKING:
    from skopaq.config import SkopaqConfig

logger = logging.getLogger(__name__)

# How old a cached quote can be before we try to refresh (seconds)
DEFAULT_STALE_THRESHOLD = 30.0

# yfinance is sync — we run it in a thread and cache aggressively
_YFINANCE_CACHE_TTL = 15.0  # seconds


class QuoteSource(Protocol):
    """Protocol for any object that can provide quotes."""

    async def get_quote(self, instrument_key: str, symbol: str = "") -> Quote: ...
    async def get_ltp(self, instrument_key: str) -> float: ...


class MarketDataProvider:
    """Multi-source market data provider with automatic fallback.

    Sources are tried in order: broker API → yfinance → cache.
    All quotes are cached locally with timestamps for staleness checks.

    Args:
        config: Application configuration.
        stale_threshold: Seconds after which a cached quote is considered stale.
    """

    def __init__(
        self,
        config: Optional[SkopaqConfig] = None,
        stale_threshold: float = DEFAULT_STALE_THRESHOLD,
    ) -> None:
        self._config = config
        self._stale_threshold = stale_threshold
        self._broker_client: Optional[Any] = None
        self._broker_type: str = config.broker if config else "indstocks"
        self._asset_class: str = config.asset_class if config else "equity"

        # Optional additional data providers
        self._angelone_client: Optional[Any] = None
        self._upstox_client: Optional[Any] = None
        self._angelone_initialized: bool = False
        self._upstox_initialized: bool = False

        # Quote cache: {symbol: (Quote, timestamp)}
        self._cache: dict[str, tuple[Quote, float]] = {}

    def set_broker_client(self, client: Any) -> None:
        """Attach a live broker client (INDstocksClient or KiteConnectClient).

        When set, the provider uses the broker API as the primary data source.
        When not set, falls back to other providers.
        """
        self._broker_client = client

    def set_angelone_client(self, client: Any) -> None:
        """Attach an Angel One SmartAPI client for real-time data."""
        self._angelone_client = client

    def set_upstox_client(self, client: Any) -> None:
        """Attach an Upstox API client for real-time data."""
        self._upstox_client = client

    # ── Public API ────────────────────────────────────────────────────────

    async def get_quote(self, symbol: str) -> Quote:
        """Fetch a full quote for a symbol, trying all sources.

        Returns the best available quote.  Never raises — returns a
        zero-valued Quote with the symbol set on total failure.
        """
        # Check cache freshness
        cached = self._get_cached(symbol)
        if cached is not None:
            return cached

        # Source 1: Broker API (Kite/INDstocks — if available)
        quote = await self._fetch_broker_quote(symbol)
        if quote is not None and quote.ltp > 0:
            self._put_cache(symbol, quote)
            return quote

        # Source 2: Angel One SmartAPI (free, real-time, real bid/ask)
        quote = await self._fetch_angelone_quote(symbol)
        if quote is not None and quote.ltp > 0:
            self._put_cache(symbol, quote)
            return quote

        # Source 3: Upstox API (free, real-time, real bid/ask)
        quote = await self._fetch_upstox_quote(symbol)
        if quote is not None and quote.ltp > 0:
            self._put_cache(symbol, quote)
            return quote

        # Source 4: yfinance (free, no credentials — delayed, synthetic bid/ask)
        quote = await self._fetch_yfinance_quote(symbol)
        if quote is not None and quote.ltp > 0:
            self._put_cache(symbol, quote)
            return quote

        # Source 5: Binance public API (for crypto)
        if self._asset_class == "crypto":
            quote = await self._fetch_binance_quote(symbol)
            if quote is not None and quote.ltp > 0:
                self._put_cache(symbol, quote)
                return quote

        # Source 4: Return stale cache if available (better than nothing)
        stale = self._get_cached(symbol, ignore_staleness=True)
        if stale is not None:
            logger.warning(
                "All sources failed for %s — returning stale quote (LTP=%.2f)",
                symbol, stale.ltp,
            )
            return stale

        logger.warning("No market data available for %s from any source", symbol)
        return Quote(symbol=symbol)

    async def get_ltp(self, symbol: str) -> float:
        """Fetch just the last traded price.  Returns 0.0 on failure."""
        quote = await self.get_quote(symbol)
        return quote.ltp

    async def get_quotes(self, symbols: list[str]) -> list[Quote]:
        """Fetch quotes for multiple symbols concurrently."""
        tasks = [self.get_quote(sym) for sym in symbols]
        return await asyncio.gather(*tasks)

    def inject_quote(self, quote: Quote) -> None:
        """Manually inject a quote into the cache (for WebSocket feeds)."""
        self._put_cache(quote.symbol, quote)

    # ── Broker source ─────────────────────────────────────────────────────

    async def _fetch_broker_quote(self, symbol: str) -> Optional[Quote]:
        """Fetch quote from the configured broker API."""
        if self._broker_client is None:
            return None

        try:
            if self._broker_type == "kite":
                instrument_key = f"NSE:{symbol}" if ":" not in symbol else symbol
                return await self._broker_client.get_quote(
                    instrument_key, symbol=symbol,
                )
            else:
                # INDstocks — need to resolve scrip code
                from skopaq.broker.scrip_resolver import resolve_scrip_code

                scrip_code = await resolve_scrip_code(
                    self._broker_client, symbol,
                )
                return await self._broker_client.get_quote(
                    scrip_code, symbol=symbol,
                )
        except Exception:
            logger.debug(
                "Broker quote fetch failed for %s", symbol, exc_info=True,
            )
            return None

    async def _fetch_broker_ltp(self, symbol: str) -> float:
        """Fetch LTP from the configured broker API."""
        if self._broker_client is None:
            return 0.0

        try:
            if self._broker_type == "kite":
                instrument_key = f"NSE:{symbol}" if ":" not in symbol else symbol
                return await self._broker_client.get_ltp(instrument_key)
            else:
                from skopaq.broker.scrip_resolver import resolve_scrip_code

                scrip_code = await resolve_scrip_code(
                    self._broker_client, symbol,
                )
                return await self._broker_client.get_ltp(scrip_code)
        except Exception:
            logger.debug(
                "Broker LTP fetch failed for %s", symbol, exc_info=True,
            )
            return 0.0

    # ── Angel One source ──────────────────────────────────────────────────

    async def _fetch_angelone_quote(self, symbol: str) -> Optional[Quote]:
        """Fetch quote from Angel One SmartAPI (free, real-time, real bid/ask).

        Auto-initializes on first call if credentials are configured.
        """
        if self._angelone_client is None and not self._angelone_initialized:
            self._angelone_initialized = True
            self._angelone_client = await self._try_init_angelone()

        if self._angelone_client is None:
            return None

        try:
            return await self._angelone_client.get_quote(symbol)
        except Exception:
            logger.debug(
                "Angel One quote failed for %s", symbol, exc_info=True,
            )
            return None

    async def _try_init_angelone(self) -> Optional[Any]:
        """Try to initialize Angel One client from config credentials."""
        if self._config is None:
            return None
        api_key = self._config.angelone_api_key.get_secret_value()
        client_id = self._config.angelone_client_id
        password = self._config.angelone_password.get_secret_value()
        if not (api_key and client_id and password):
            return None
        try:
            from skopaq.broker.angelone_client import AngelOneClient
            totp = self._config.angelone_totp_secret.get_secret_value()
            client = AngelOneClient(
                api_key=api_key,
                client_id=client_id,
                password=password,
                totp_secret=totp,
            )
            await client.__aenter__()
            logger.info("Angel One SmartAPI connected (free real-time data)")
            return client
        except Exception:
            logger.debug("Angel One init failed — skipping", exc_info=True)
            return None

    # ── Upstox source ────────────────────────────────────────────────────

    async def _fetch_upstox_quote(self, symbol: str) -> Optional[Quote]:
        """Fetch quote from Upstox API (free, real-time, real bid/ask).

        Auto-initializes on first call if credentials are configured.
        """
        if self._upstox_client is None and not self._upstox_initialized:
            self._upstox_initialized = True
            self._upstox_client = await self._try_init_upstox()

        if self._upstox_client is None:
            return None

        try:
            return await self._upstox_client.get_quote(symbol)
        except Exception:
            logger.debug(
                "Upstox quote failed for %s", symbol, exc_info=True,
            )
            return None

    async def _try_init_upstox(self) -> Optional[Any]:
        """Try to initialize Upstox client from config credentials."""
        if self._config is None:
            return None
        access_token = self._config.upstox_access_token.get_secret_value()
        if not access_token:
            return None
        try:
            from skopaq.broker.upstox_client import UpstoxClient
            client = UpstoxClient(access_token=access_token)
            await client.__aenter__()
            logger.info("Upstox API connected (free real-time data)")
            return client
        except Exception:
            logger.debug("Upstox init failed — skipping", exc_info=True)
            return None

    # ── yfinance source ───────────────────────────────────────────────────

    async def _fetch_yfinance_quote(self, symbol: str) -> Optional[Quote]:
        """Fetch quote from yfinance (free, no credentials needed).

        yfinance is synchronous, so we run it in a thread.
        Indian stocks need ``.NS`` suffix, crypto uses ``BTC-USD`` format.
        """
        try:
            return await asyncio.to_thread(self._yfinance_sync, symbol)
        except Exception:
            logger.debug(
                "yfinance quote failed for %s", symbol, exc_info=True,
            )
            return None

    @staticmethod
    def _yfinance_sync(symbol: str) -> Optional[Quote]:
        """Synchronous yfinance fetch (runs in thread)."""
        try:
            import yfinance as yf
        except ImportError:
            logger.debug("yfinance not installed — skipping fallback source")
            return None

        # Build the yfinance symbol
        yf_symbol = _to_yfinance_symbol(symbol)

        try:
            ticker = yf.Ticker(yf_symbol)
            info = ticker.fast_info

            ltp = getattr(info, "last_price", 0) or 0
            if ltp <= 0:
                return None

            day_high = getattr(info, "day_high", 0) or 0
            day_low = getattr(info, "day_low", 0) or 0
            open_price = getattr(info, "open", 0) or 0
            prev_close = getattr(info, "previous_close", 0) or 0
            volume = getattr(info, "last_volume", 0) or 0

            change = round(ltp - prev_close, 2) if prev_close else 0.0
            change_pct = round(
                (change / prev_close) * 100, 2
            ) if prev_close else 0.0

            # yfinance doesn't give bid/ask from fast_info — estimate spread
            spread = ltp * 0.001  # 0.1% estimated spread
            bid = round(ltp - spread / 2, 2)
            ask = round(ltp + spread / 2, 2)

            return Quote(
                symbol=symbol,  # Return original symbol, not yfinance format
                exchange="NSE",
                ltp=round(float(ltp), 2),
                open=round(float(open_price), 2),
                high=round(float(day_high), 2),
                low=round(float(day_low), 2),
                close=round(float(prev_close), 2),
                volume=int(volume),
                change=change,
                change_pct=change_pct,
                bid=bid,
                ask=ask,
                timestamp=datetime.now(timezone.utc),
            )
        except Exception:
            logger.debug(
                "yfinance data extraction failed for %s", yf_symbol,
                exc_info=True,
            )
            return None

    # ── Binance public source (crypto) ─────────────────────────────────────

    async def _fetch_binance_quote(self, symbol: str) -> Optional[Quote]:
        """Fetch quote from Binance public API (no auth needed, crypto only)."""
        try:
            from skopaq.broker.binance_client import BinanceClient
            from skopaq.broker.crypto_symbols import to_binance_pair

            pair = to_binance_pair(symbol)
            base_url = (
                self._config.binance_base_url
                if self._config
                else "https://api.binance.com"
            )
            client = BinanceClient(base_url=base_url)

            async with client:
                quote = await client.get_quote(pair)
                # Preserve original symbol name
                quote.symbol = symbol
                return quote
        except Exception:
            logger.debug(
                "Binance quote failed for %s", symbol, exc_info=True,
            )
            return None

    # ── Cache management ──────────────────────────────────────────────────

    def _get_cached(
        self, symbol: str, ignore_staleness: bool = False,
    ) -> Optional[Quote]:
        """Return cached quote if fresh enough."""
        entry = self._cache.get(symbol)
        if entry is None:
            return None

        quote, ts = entry
        age = time.monotonic() - ts

        if ignore_staleness or age <= self._stale_threshold:
            return quote
        return None

    def _put_cache(self, symbol: str, quote: Quote) -> None:
        """Store a quote in the cache with current timestamp."""
        self._cache[symbol] = (quote, time.monotonic())

    def clear_cache(self) -> None:
        """Clear all cached quotes."""
        self._cache.clear()


def _to_yfinance_symbol(symbol: str) -> str:
    """Convert a trading symbol to yfinance format.

    Rules:
        RELIANCE     → RELIANCE.NS  (Indian equity on NSE)
        RELIANCE.NS  → RELIANCE.NS  (already formatted)
        RELIANCE.BO  → RELIANCE.BO  (BSE)
        BTCUSDT      → BTC-USD      (crypto)
        BTC-USD      → BTC-USD      (already formatted)
        NSE:RELIANCE → RELIANCE.NS  (strip Kite prefix)
    """
    # Strip Kite-style prefix
    if ":" in symbol:
        parts = symbol.split(":", 1)
        exchange = parts[0].upper()
        sym = parts[1]
        if exchange == "BSE":
            return f"{sym}.BO"
        return f"{sym}.NS"

    # Already has yfinance suffix
    if symbol.endswith((".NS", ".BO", "-USD")):
        return symbol

    # Crypto detection (ends with USDT, BUSD, etc.)
    crypto_quotes = ("USDT", "BUSD", "USDC", "BTC", "ETH")
    for quote_currency in crypto_quotes:
        if symbol.endswith(quote_currency) and len(symbol) > len(quote_currency):
            base = symbol[: -len(quote_currency)]
            return f"{base}-USD"

    # Default: Indian equity on NSE
    return f"{symbol}.NS"

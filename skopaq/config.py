"""SkopaqTrader configuration — loaded from environment variables and .env file."""

from __future__ import annotations

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SkopaqConfig(BaseSettings):
    """Central configuration for SkopaqTrader.

    All values are read from environment variables prefixed with ``SKOPAQ_``.
    A ``.env`` file in the project root is loaded automatically.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SKOPAQ_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Supabase ────────────────────────────────────────────────────────
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: SecretStr = SecretStr("")

    # ── Upstash Redis ───────────────────────────────────────────────────
    upstash_redis_url: str = ""
    upstash_redis_token: SecretStr = SecretStr("")

    # ── INDstocks Broker ────────────────────────────────────────────────
    indstocks_token: SecretStr = SecretStr("")
    indstocks_base_url: str = "https://api.indstocks.com"
    indstocks_ws_price_url: str = "wss://ws-prices.indstocks.com/api/v1/ws/prices"
    indstocks_ws_order_url: str = "wss://ws-order-updates.indstocks.com"

    # ── Trading Mode ────────────────────────────────────────────────────
    trading_mode: Literal["paper", "live"] = "paper"
    initial_paper_capital: float = 1_000_000.0  # INR

    # ── LLM API Keys ───────────────────────────────────────────────────
    google_api_key: SecretStr = SecretStr("")  # Gemini Flash (scanner)
    anthropic_api_key: SecretStr = SecretStr("")  # Claude Sonnet (analysis)
    perplexity_api_key: SecretStr = SecretStr("")  # Sonar (news)
    xai_api_key: SecretStr = SecretStr("")  # Grok (sentiment)
    openrouter_api_key: SecretStr = SecretStr("")  # OpenRouter (Grok + Perplexity)

    # ── Cloudflare Tunnel ───────────────────────────────────────────────
    cf_tunnel_id: str = ""

    # ── Scanner ────────────────────────────────────────────────────────
    scanner_enabled: bool = False
    scanner_cycle_seconds: int = 30
    scanner_max_candidates: int = 5

    # ── API Server ──────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ── Reflection / Memory ─────────────────────────────────────────────
    reflection_enabled: bool = True
    reflection_max_memory_entries: int = 50

    # ── Upstream Agent Tuning ─────────────────────────────────────────
    max_debate_rounds: int = 1
    max_risk_discuss_rounds: int = 1
    selected_analysts: str = "market,social,news,fundamentals"
    google_thinking_level: str = ""

    # ── Risk-Adjusted Position Sizing ─────────────────────────────────
    position_sizing_enabled: bool = True
    risk_per_trade_pct: float = 0.01     # 1% of equity per trade
    atr_multiplier: float = 2.0          # Stop distance in ATR units
    atr_period: int = 14                 # ATR lookback period

    # ── Sector Concentration ──────────────────────────────────────────
    max_sector_concentration_pct: float = 0.40  # Max 40% in any one sector

    # ── Regime Detection ──────────────────────────────────────────────
    regime_detection_enabled: bool = False  # Off until tested with live data

    # ── Semantic Cache (Redis LangCache) ────────────────────────────────
    langcache_enabled: bool = False
    langcache_api_key: SecretStr = SecretStr("")
    langcache_server_url: str = ""
    langcache_cache_id: str = ""
    langcache_threshold: float = 0.90  # Cosine similarity threshold (0–1)

    # ── Asset Class ──────────────────────────────────────────────────────
    asset_class: Literal["equity", "crypto"] = "equity"
    crypto_quote_currency: str = "USDT"
    binance_base_url: str = "https://api.binance.com"

    # ── Logging ─────────────────────────────────────────────────────────
    log_level: str = "INFO"

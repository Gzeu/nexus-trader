"""
config.py – Pydantic v2 Settings, loaded once via @lru_cache singleton.
All values read from environment / .env file.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Environment ────────────────────────────────────────────────────
    environment: str = Field(
        default="development",
        pattern="^(development|staging|production)$",
        description="Runtime environment: development | staging | production",
    )

    # ── Exchange ──────────────────────────────────────────────────────────
    binance_api_key: str = Field(default="", description="Binance API key")
    binance_api_secret: str = Field(default="", description="Binance API secret")
    testnet: bool = Field(default=True, description="Use Binance testnet")
    dry_run: bool = Field(default=True, description="Simulate orders, never send real ones")

    # ── Mode ──────────────────────────────────────────────────────────────
    market_mode: str = Field(default="spot", pattern="^(spot|futures)$")
    futures_enabled: bool = Field(default=False)
    default_leverage: int = Field(default=1, ge=1, le=125)

    # ── Risk ───────────────────────────────────────────────────────────────
    risk_per_trade: float = Field(default=0.01, gt=0, le=0.05)
    max_positions: int = Field(default=5, ge=1, le=20)
    max_daily_loss: float = Field(default=0.03, gt=0, le=0.20)
    max_drawdown: float = Field(default=0.12, gt=0, le=0.50)
    min_rr: float = Field(default=1.5, ge=1.0, le=10.0)
    cooldown_minutes: int = Field(default=20, ge=0)
    max_consecutive_losses: int = Field(default=3, ge=1)

    # ── Volatility / Spread filters ──────────────────────────────────────────
    atr_max_pct: float = Field(default=0.05, gt=0)
    spread_max_pct: float = Field(default=0.002, gt=0)

    # ── Execution ───────────────────────────────────────────────────────────────
    order_timeout_sec: float = Field(default=10.0, gt=0)
    retry_max_attempts: int = Field(default=3, ge=1)
    retry_base_delay: float = Field(default=0.5, gt=0)
    retry_max_delay: float = Field(default=8.0, gt=0)
    exchange_info_ttl_seconds: int = Field(default=1800, ge=60)
    max_retries: int = Field(default=3, ge=1)

    # ── Automation ─────────────────────────────────────────────────────────────
    automation_interval_sec: int = Field(default=60, ge=5)
    strategy_interval_seconds: int = Field(default=60, ge=5)
    strategy_timeframe: str = Field(default="15m")
    symbols: str = Field(default="BTCUSDT,ETHUSDT")
    symbol_whitelist: str = Field(default="BTCUSDT,ETHUSDT")
    symbol_blacklist: str = Field(default="")

    # ── Journal ──────────────────────────────────────────────────────────────
    journal_csv_path: str = Field(default="journal/trades.csv")
    journal_db_path: str = Field(default="journal/trades.db")

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")

    # ── Redis ──────────────────────────────────────────────────────────────
    redis_url: str = Field(default="")

    # ── Server ───────────────────────────────────────────────────────────────
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    secret_key: str = Field(default="change_me")
    log_level: str = Field(default="INFO")
    # Comma-separated origins allowed for CORS — e.g. http://localhost:3000,https://myapp.com
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000",
        description="Comma-separated CORS allowed origins",
    )

    # ── Derived helpers ────────────────────────────────────────────────────────────
    @property
    def symbols_list(self) -> List[str]:
        return [s.strip().upper() for s in self.symbols.split(",") if s.strip()]

    @property
    def blacklist_set(self) -> set:
        return {s.strip().upper() for s in self.symbol_blacklist.split(",") if s.strip()}

    @property
    def allowed_symbols(self) -> List[str]:
        return [s for s in self.symbols_list if s not in self.blacklist_set]

    @property
    def cors_origins_list(self) -> List[str]:
        """Return CORS_ORIGINS as a parsed list, stripping whitespace."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @field_validator("market_mode")
    @classmethod
    def normalize_mode(cls, v: str) -> str:
        return v.lower()

    @field_validator("environment")
    @classmethod
    def normalize_env(cls, v: str) -> str:
        return v.lower()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    return Settings()

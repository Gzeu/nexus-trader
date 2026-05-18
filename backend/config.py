"""
config.py – Pydantic v2 Settings loaded from .env / environment.
All risk constants, execution tunables, and feature flags live here.
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

    # ── Mode ──────────────────────────────────────────────────────
    dry_run: bool = True
    testnet: bool = True
    log_level: str = "INFO"
    env: str = "development"

    # ── Binance ─────────────────────────────────────────────────
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet_base_url: str = "https://testnet.binance.vision"
    binance_base_url: str = "https://api.binance.com"

    # ── Risk ─────────────────────────────────────────────────────
    max_positions: int = Field(default=3, ge=1, le=10)
    risk_per_trade: float = Field(default=0.01, ge=0.001, le=0.05)
    max_daily_loss: float = Field(default=0.03, ge=0.01, le=0.20)
    max_drawdown: float = Field(default=0.12, ge=0.05, le=0.50)
    min_rr: float = Field(default=1.5, ge=1.0)
    cooldown_minutes: int = Field(default=15, ge=0)
    max_consecutive_losses: int = Field(default=3, ge=1)

    # ── Execution ────────────────────────────────────────────────
    order_timeout_seconds: int = Field(default=10, ge=1)
    max_retries: int = Field(default=3, ge=0)
    retry_base_delay: float = Field(default=0.5, ge=0.1)
    use_redis: bool = False
    redis_url: str = "redis://localhost:6379/0"

    # ── Telegram ────────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── DB ─────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./journal.db"

    # ── Symbols ──────────────────────────────────────────────────────
    spot_whitelist: List[str] = ["BTCUSDT", "ETHUSDT"]
    futures_whitelist: List[str] = ["BTCUSDT", "ETHUSDT"]
    default_leverage: int = Field(default=5, ge=1, le=125)

    @field_validator("spot_whitelist", "futures_whitelist", mode="before")
    @classmethod
    def parse_csv(cls, v: str | list) -> list:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def binance_base(self) -> str:
        return self.binance_testnet_base_url if self.testnet else self.binance_base_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()

"""
config.py – Nexus Trader v3 Settings.

Improvements over v2:
- pydantic_settings v2 with model_config
- Custom field validators (RISK_PER_TRADE range, API key format)
- SPOT_WHITELIST / FUTURES_WHITELIST separate
- Per-symbol overrides dict (leverage, mode, max_position_size)
- exchange_info TTL constant
- Weekly risk cap added
- scan_interval_seconds validates > 0
"""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Binance credentials ──────────────────────────────────────────────
    binance_api_key: str = Field(..., min_length=10)
    binance_api_secret: str = Field(..., min_length=10)
    binance_futures_api_key: Optional[str] = None
    binance_futures_api_secret: Optional[str] = None

    # ── Environment ──────────────────────────────────────────────────────
    testnet: bool = True
    dry_run: bool = True
    debug: bool = False
    environment: str = "development"  # development | staging | production

    # ── Market modes ─────────────────────────────────────────────────────
    futures_enabled: bool = False
    futures_market_mode: str = "FUTURES"  # FUTURES | SPOT
    spot_market_mode: str = "SPOT"

    # ── Symbol configuration ──────────────────────────────────────────────
    spot_whitelist: List[str] = ["BTCUSDT", "ETHUSDT"]
    futures_whitelist: List[str] = ["BTCUSDT", "ETHUSDT"]
    symbol_blacklist: List[str] = []
    leverage_default: int = Field(default=1, ge=1, le=125)
    primary_timeframe: str = "15m"

    # Per-symbol overrides: {"BTCUSDT": {"leverage": 3, "max_position_pct": 0.05}}
    symbol_config: Dict[str, Dict] = {}

    # ── Risk parameters ───────────────────────────────────────────────────
    risk_per_trade: float = Field(default=0.01, ge=0.001, le=0.05)
    max_positions: int = Field(default=3, ge=1, le=20)
    max_daily_loss: float = Field(default=0.03, ge=0.005, le=0.20)
    max_weekly_loss: float = Field(default=0.07, ge=0.01, le=0.30)
    max_drawdown: float = Field(default=0.12, ge=0.03, le=0.50)
    min_rr: float = Field(default=1.5, ge=1.0, le=10.0)
    cooldown_minutes: int = Field(default=15, ge=0, le=240)
    max_consecutive_losses: int = Field(default=3, ge=1, le=20)
    min_confidence: float = Field(default=0.60, ge=0.0, le=1.0)
    min_consensus: float = Field(default=0.55, ge=0.0, le=1.0)

    # ── ATR volatility filter ─────────────────────────────────────────────
    atr_period: int = Field(default=14, ge=5, le=50)
    atr_multiplier_sl: float = Field(default=1.5, ge=0.5, le=5.0)
    atr_multiplier_tp: float = Field(default=2.5, ge=1.0, le=10.0)
    max_atr_pct: float = Field(default=0.05, ge=0.001, le=0.20)  # volatility gate

    # ── Execution ─────────────────────────────────────────────────────────
    order_timeout_seconds: int = Field(default=30, ge=5, le=300)
    max_retries: int = Field(default=3, ge=1, le=10)
    retry_base_delay: float = Field(default=1.0, ge=0.1, le=30.0)
    retry_max_delay: float = Field(default=30.0, ge=1.0, le=300.0)
    exchange_info_ttl_seconds: int = Field(default=1800, ge=60)  # 30 min cache
    partial_close_tp1_pct: float = Field(default=0.40, ge=0.10, le=0.90)
    partial_close_tp2_pct: float = Field(default=0.40, ge=0.10, le=0.90)

    # ── Scan / automation ─────────────────────────────────────────────────
    scan_interval_seconds: int = Field(default=60, ge=5)
    reconcile_interval_seconds: int = Field(default=300, ge=30)
    max_holding_hours: float = Field(default=72.0, ge=1.0)
    inactivity_hours: float = Field(default=24.0, ge=1.0)

    # ── API server ────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1024, le=65535)
    api_secret_key: str = Field(default="change-me-in-production", min_length=16)
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    # ── Telegram ──────────────────────────────────────────────────────────
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_enabled: bool = False

    # ── Redis (optional idempotency store) ────────────────────────────────
    redis_url: Optional[str] = None  # e.g. redis://localhost:6379/0

    # ── Database ─────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./nexus_trader.db"
    journal_csv_path: str = "./journal/trades.csv"

    # ── Validators ────────────────────────────────────────────────────────

    @field_validator("spot_whitelist", "futures_whitelist", mode="before")
    @classmethod
    def parse_symbol_list(cls, v):
        if isinstance(v, str):
            return [s.strip().upper() for s in v.split(",") if s.strip()]
        return [s.upper() for s in v]

    @field_validator("symbol_blacklist", mode="before")
    @classmethod
    def parse_blacklist(cls, v):
        if isinstance(v, str):
            return [s.strip().upper() for s in v.split(",") if s.strip()]
        return [s.upper() for s in v]

    @field_validator("primary_timeframe")
    @classmethod
    def validate_timeframe(cls, v: str) -> str:
        valid = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"}
        if v not in valid:
            raise ValueError(f"primary_timeframe must be one of {valid}")
        return v

    @model_validator(mode="after")
    def validate_risk_consistency(self) -> "Settings":
        if self.max_daily_loss >= self.max_drawdown:
            raise ValueError("max_daily_loss must be < max_drawdown")
        if self.max_weekly_loss >= self.max_drawdown:
            raise ValueError("max_weekly_loss must be < max_drawdown")
        if self.retry_base_delay >= self.retry_max_delay:
            raise ValueError("retry_base_delay must be < retry_max_delay")
        return self

    @model_validator(mode="after")
    def validate_futures_credentials(self) -> "Settings":
        if self.futures_enabled and not self.testnet:
            if not self.binance_futures_api_key or not self.binance_futures_api_secret:
                raise ValueError(
                    "BINANCE_FUTURES_API_KEY and BINANCE_FUTURES_API_SECRET required "
                    "when futures_enabled=True and testnet=False"
                )
        return self

    # ── Helpers ───────────────────────────────────────────────────────────

    @property
    def symbol_whitelist(self) -> List[str]:
        """Unified whitelist: futures symbols if futures_enabled, else spot."""
        base = self.futures_whitelist if self.futures_enabled else self.spot_whitelist
        return [s for s in base if s not in self.symbol_blacklist]

    def get_symbol_leverage(self, symbol: str) -> int:
        """Return per-symbol leverage override or default."""
        return self.symbol_config.get(symbol, {}).get("leverage", self.leverage_default)

    def get_symbol_max_position_pct(self, symbol: str) -> float:
        """Return per-symbol max position size as fraction of equity."""
        return self.symbol_config.get(symbol, {}).get("max_position_pct", 0.10)

    def is_telegram_configured(self) -> bool:
        return bool(
            self.telegram_enabled
            and self.telegram_bot_token
            and self.telegram_chat_id
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton — call get_settings() everywhere."""
    return Settings()

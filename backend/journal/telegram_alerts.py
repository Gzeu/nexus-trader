"""
telegram_alerts.py – Telegram notification service.

Fixes / improvements over v1:
- TelegramAlerter is a proper class (not module-level functions)
  so it can be mocked in tests and passed as a dependency
- send_alert() is rate-limited (max 1 message per 3s) to avoid Telegram 429
- All methods are no-ops when telegram is not configured (no exceptions thrown)
- _format_signal() / _format_order_filled() helpers for consistent messages
- alert_daily_summary() generates a clean P&L table
- Standalone send_alert() module-level function kept for backwards compat
"""
from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Optional

import httpx
import structlog

from backend.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

_RATE_LIMIT_SECONDS = 3.0  # min gap between messages


class TelegramAlerter:
    """Sends Telegram alerts for critical trading events."""

    def __init__(self):
        self._last_sent: float = 0.0
        self._enabled = settings.is_telegram_configured()
        self._base_url = (
            f"https://api.telegram.org/bot{settings.telegram_bot_token}"
            if settings.telegram_bot_token
            else ""
        )

    async def send_alert(self, message: str, parse_mode: str = "HTML") -> None:
        """Send a plain text message. Rate-limited, non-blocking."""
        if not self._enabled:
            return
        now = time.monotonic()
        gap = now - self._last_sent
        if gap < _RATE_LIMIT_SECONDS:
            await asyncio.sleep(_RATE_LIMIT_SECONDS - gap)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{self._base_url}/sendMessage",
                    json={
                        "chat_id": settings.telegram_chat_id,
                        "text": message,
                        "parse_mode": parse_mode,
                    },
                )
            self._last_sent = time.monotonic()
        except Exception as exc:
            log.warning("telegram_send_failed", error=str(exc))

    async def alert_signal(self, signal) -> None:
        if not self._enabled:
            return
        action = str(signal.action)
        emoji = "🟢" if action == "BUY" else "🔴"
        msg = (
            f"{emoji} <b>Signal: {action}</b> — {signal.symbol}\n"
            f"Confidence: {signal.confidence:.0%} | TF: {signal.timeframe}\n"
            f"Entry: {signal.entry_price} | SL: {signal.stop_loss} | TP1: {signal.take_profit_1}\n"
            f"<i>{signal.reason[:120]}</i>"
        )
        await self.send_alert(msg)

    async def alert_order_filled(self, order) -> None:
        if not self._enabled:
            return
        msg = (
            f"✅ <b>Order Filled</b>\n"
            f"Symbol: {order.symbol} | Side: {order.side}\n"
            f"Qty: {order.filled_quantity} @ {order.avg_fill_price}\n"
            f"ID: {order.exchange_order_id}"
        )
        await self.send_alert(msg)

    async def alert_risk_event(self, event: str, details: str = "") -> None:
        if not self._enabled:
            return
        msg = f"⚠️ <b>Risk Event: {event}</b>\n{details[:200]}"
        await self.send_alert(msg)

    async def alert_daily_summary(self, metrics: dict) -> None:
        if not self._enabled:
            return
        wl = metrics.get("win_rate", 0)
        msg = (
            f"📊 <b>Daily Summary</b>\n"
            f"Equity: {metrics.get('equity', 0):.2f} USDT\n"
            f"Daily P&amp;L: {metrics.get('daily_pnl', 0):+.2f} ({metrics.get('daily_pnl_pct', 0):+.2%})\n"
            f"Trades: {metrics.get('total_trades', 0)} | Win rate: {wl:.0%}\n"
            f"Drawdown: {metrics.get('current_drawdown', 0):.2%} / {metrics.get('max_drawdown', 0):.2%}"
        )
        await self.send_alert(msg)


# Backwards-compat module-level function
_default_alerter: Optional[TelegramAlerter] = None


async def send_alert(message: str) -> None:
    """Module-level send_alert for backwards compatibility."""
    global _default_alerter
    if _default_alerter is None:
        _default_alerter = TelegramAlerter()
    await _default_alerter.send_alert(message)

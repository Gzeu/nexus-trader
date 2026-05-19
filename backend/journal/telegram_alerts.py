"""
TelegramAlerter — notificari async pentru evenimente critice.
Nu arunca exceptii — logeaza si continua.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from backend.models import Order, StrategySignal, Trade

logger = logging.getLogger(__name__)


class TelegramAlerter:
    """Trimite mesaje Markdown la un chat Telegram."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id
        self._base = f"https://api.telegram.org/bot{token}/sendMessage"
        self._enabled = bool(token and chat_id)

    async def send_alert(self, text: str) -> None:
        """Trimite un mesaj simplu Markdown."""
        if not self._enabled:
            logger.debug("Telegram disabled — skipping: %s", text[:60])
            return
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    self._base,
                    json={"chat_id": self._chat_id, "text": text, "parse_mode": "Markdown"},
                )
        except Exception as exc:
            logger.warning("Telegram send failed: %s", exc)

    async def alert_signal(self, signal: StrategySignal) -> None:
        emoji = "🟢" if signal.action in ("BUY", "LONG") else "🔴" if signal.action in ("SELL", "SHORT") else "⚪"
        msg = (
            f"{emoji} *{signal.action}* `{signal.symbol}`\n"
            f"Confidence: `{signal.confidence:.0%}`\n"
            f"Entry: `{signal.entry_price}`  SL: `{signal.stop_loss}`\n"
            f"TP1: `{signal.take_profit_1}`  TP2: `{signal.take_profit_2}`\n"
            f"Reason: _{signal.reason}_"
        )
        await self.send_alert(msg)

    async def alert_order_filled(self, order: Order) -> None:
        msg = (
            f"✅ *Order Filled* `{order.symbol}`\n"
            f"Side: `{order.side}`  Qty: `{order.quantity}`\n"
            f"Price: `{order.price}`  ID: `{order.id}`"
        )
        await self.send_alert(msg)

    async def alert_risk_event(self, event: str, detail: str = "") -> None:
        msg = f"⚠️ *Risk Event*: {event}\n{detail}"
        await self.send_alert(msg)

    async def alert_daily_summary(
        self,
        equity: float,
        pnl_today: float,
        win_rate: float,
        trades_today: int,
    ) -> None:
        direction = "📈" if pnl_today >= 0 else "📉"
        msg = (
            f"{direction} *Daily Summary*\n"
            f"Equity: `${equity:,.2f}`\n"
            f"PnL Today: `{'+' if pnl_today >= 0 else ''}{pnl_today:,.2f} USDT`\n"
            f"Win Rate: `{win_rate:.0%}`  Trades: `{trades_today}`"
        )
        await self.send_alert(msg)

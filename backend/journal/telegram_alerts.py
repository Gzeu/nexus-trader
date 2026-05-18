"""
telegram_alerts.py – Async Telegram notifications for critical events.

Sent on:
  - Signal created / rejected
  - Order filled
  - Risk veto (drawdown, daily loss, cooldown, emergency stop)
  - Daily PnL summary
  - System startup / shutdown
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
import structlog

from backend.config import get_settings

log = structlog.get_logger(__name__)


async def send_alert(text: str) -> None:
    """Send a plain-text message to the configured Telegram chat."""
    s = get_settings()
    if not s.telegram_bot_token or not s.telegram_chat_id:
        log.debug("telegram_disabled")
        return
    url = f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": s.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(url, json=payload)
            if r.status_code != 200:
                log.warning("telegram_send_failed", status=r.status_code, body=r.text)
    except Exception as exc:
        log.error("telegram_error", error=str(exc))


async def alert_signal(signal: Dict[str, Any], accepted: bool, veto: Optional[str] = None) -> None:
    icon = "✅" if accepted else "❌"
    msg = (
        f"{icon} <b>Signal</b> {signal.get('action')} {signal.get('symbol')}\n"
        f"Confidence: {signal.get('confidence', 0):.2f} | TF: {signal.get('timeframe')}\n"
        f"Entry: {signal.get('entry_price')} | SL: {signal.get('stop_loss')} | TP1: {signal.get('take_profit_1')}\n"
        f"Reason: {signal.get('reason', '')}"
    )
    if not accepted and veto:
        msg += f"\n⛔ Veto: {veto}"
    await send_alert(msg)


async def alert_order_filled(order: Dict[str, Any]) -> None:
    side_icon = "🟢" if order.get("side", "").upper() == "BUY" else "🔴"
    msg = (
        f"{side_icon} <b>Order Filled</b>\n"
        f"{order.get('symbol')} {order.get('side')} @ {order.get('price')}\n"
        f"Qty: {order.get('executed_qty')} | Status: {order.get('status')}"
    )
    await send_alert(msg)


async def alert_risk_event(event: str, detail: str) -> None:
    msg = f"⚠️ <b>Risk Event</b>: {event}\n{detail}"
    await send_alert(msg)


async def alert_daily_summary(stats: Dict[str, Any]) -> None:
    pnl = stats.get("daily_pnl", 0)
    icon = "📈" if pnl >= 0 else "📉"
    msg = (
        f"{icon} <b>Daily Summary</b>\n"
        f"PnL: {pnl:+.2f} USDT ({stats.get('daily_pnl_pct', 0):+.2f}%)\n"
        f"Trades: {stats.get('trades_today', 0)} | Win rate: {stats.get('win_rate', 0):.1f}%\n"
        f"Equity: {stats.get('equity', 0):.2f} USDT"
    )
    await send_alert(msg)

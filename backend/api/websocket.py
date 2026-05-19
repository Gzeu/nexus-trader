"""
websocket.py – WebSocket hub for live TradingView sync.

Fixes / improvements over v1:
- ConnectionManager.broadcast() catches per-client send errors
- Stale connections removed from active set on send error
- Heartbeat task sends HEARTBEAT event every 15s
- ws_broadcast callable registered on app.state.ctx at connection time
- Proper JSON serialization for datetime fields

COMPLETARE 3: broadcast_raw() now handles WSEventType.RISK_EVENT:
- CRITICAL severity → log.critical() + Telegram alert
- WARNING severity  → log.warning()
- Payload enriched with UTC timestamp
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Optional, Set

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

from backend.models import WSEvent, WSEventType

log = structlog.get_logger(__name__)
router = APIRouter()


class ConnectionManager:
    """Thread-safe (asyncio) WebSocket connection manager."""

    def __init__(self):
        self._active: Set[WebSocket] = set()
        self._telegram = None  # injected from app.state.ctx at startup

    def set_telegram(self, telegram) -> None:
        """Inject Telegram alert client for RISK_EVENT notifications."""
        self._telegram = telegram

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)
        log.info("ws_connected", total=len(self._active))

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)
        log.info("ws_disconnected", total=len(self._active))

    async def broadcast(self, event: WSEvent) -> None:
        """Broadcast to all connected clients. Remove stale connections silently."""
        if not self._active:
            return
        message = event.model_dump_json()
        stale: list[WebSocket] = []
        for ws in list(self._active):
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(message)
                else:
                    stale.append(ws)
            except Exception as exc:
                log.warning("ws_send_error", error=str(exc))
                stale.append(ws)
        for ws in stale:
            self._active.discard(ws)

    async def broadcast_raw(self, event_type: WSEventType, payload: dict) -> None:
        """
        Convenience wrapper used by execution_engine and automation_engine.

        COMPLETARE 3: Handles RISK_EVENT with severity-aware logging and
        Telegram alerts for critical events.
        """
        # Enrich payload with timestamp for all events
        enriched = {
            **payload,
            "ts": datetime.utcnow().isoformat(),
            "event_type": event_type.value if hasattr(event_type, "value") else str(event_type),
        }

        # Handle RISK_EVENT with severity routing
        if event_type == WSEventType.RISK_EVENT:
            severity = payload.get("severity", "WARNING")
            symbol   = payload.get("symbol", "UNKNOWN")
            detail   = payload.get("detail", "")
            event    = payload.get("event", "RISK_EVENT")

            if severity == "CRITICAL":
                log.critical(
                    "risk_event_critical",
                    symbol=symbol,
                    event=event,
                    detail=detail,
                )
                # Fire Telegram alert for critical risk events
                if self._telegram is not None:
                    try:
                        await self._telegram.send_alert(
                            f"🚨 CRITICAL RISK EVENT\n"
                            f"Symbol: {symbol}\n"
                            f"Event: {event}\n"
                            f"Detail: {detail}\n"
                            f"Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
                        )
                    except Exception as tg_exc:
                        log.error("telegram_alert_failed", error=str(tg_exc))
            else:
                log.warning(
                    "risk_event_warning",
                    symbol=symbol,
                    event=event,
                    detail=detail,
                    severity=severity,
                )

        await self.broadcast(
            WSEvent(
                event=event_type,
                payload=enriched,
            )
        )

    @property
    def connection_count(self) -> int:
        return len(self._active)


# Singleton manager
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Main WebSocket endpoint. TradingView broker connects here."""
    app = ws.app
    await manager.connect(ws)

    # Register broadcast callable and Telegram on AppState
    if hasattr(app, "state") and hasattr(app.state, "ctx"):
        app.state.ctx.ws_broadcast = manager.broadcast_raw
        if hasattr(app.state.ctx, "telegram") and app.state.ctx.telegram:
            manager.set_telegram(app.state.ctx.telegram)

    # Start heartbeat task
    heartbeat_task = asyncio.create_task(_heartbeat(ws))

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        log.info("ws_client_disconnected")
    except Exception as exc:
        log.warning("ws_error", error=str(exc))
    finally:
        heartbeat_task.cancel()
        manager.disconnect(ws)


async def _heartbeat(ws: WebSocket, interval: int = 15) -> None:
    """Send HEARTBEAT event every `interval` seconds to keep connection alive."""
    while True:
        await asyncio.sleep(interval)
        try:
            if ws.client_state == WebSocketState.CONNECTED:
                event = WSEvent(
                    event=WSEventType.HEARTBEAT,
                    payload={"ts": datetime.utcnow().isoformat()},
                )
                await ws.send_text(event.model_dump_json())
        except Exception:
            break

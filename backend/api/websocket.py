"""
websocket.py – WebSocket hub for live TradingView sync.

Fixes / improvements over v1:
- ConnectionManager.broadcast() catches per-client send errors (one broken
  client no longer kills all others)
- Stale connections removed from active set on send error
- Heartbeat task sends HEARTBEAT event every 15s (keeps connection alive through
  proxies and load balancers)
- ws_broadcast callable registered on app.state.ctx at connection time
  so execution_engine and automation_engine can push events
- Proper JSON serialization for datetime fields
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Set

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
        """Convenience wrapper used by execution_engine and automation_engine."""
        await self.broadcast(
            WSEvent(
                event=event_type,
                payload=payload,
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

    # Register broadcast callable on AppState so all engines can push events
    if hasattr(app, "state") and hasattr(app.state, "ctx"):
        app.state.ctx.ws_broadcast = manager.broadcast_raw

    # Start heartbeat task
    heartbeat_task = asyncio.create_task(_heartbeat(ws))

    try:
        while True:
            data = await ws.receive_text()
            # Handle ping from client
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

"""
websocket.py – WebSocket broadcast hub for live TradingView UI updates.

All EventEmitter events are forwarded to every connected client.
Client reconnection + ping/pong keepalive included.
"""
from __future__ import annotations

import asyncio
import json
from typing import Set

import structlog
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

log = structlog.get_logger(__name__)
router = APIRouter()

# Global set of connected clients – safe within single-process asyncio event loop
_clients: Set[WebSocket] = set()

# Events forwarded to TradingView broker adapter
_FORWARDED_EVENTS = (
    "signal_created",
    "signal_rejected",
    "order_filled",
    "position_opened",
    "position_update_required",
    "trade_closed",
    "partial_close",
    "tp_hit",
    "sl_hit",
    "daily_loss_pause",
    "drawdown_stop",
)


async def broadcast(event: str, payload: dict) -> None:
    """Send an event to all connected WebSocket clients. Drop disconnected ones."""
    if not _clients:
        return
    message = json.dumps({"event": event, "payload": payload})
    disconnected: Set[WebSocket] = set()
    for ws in _clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    _clients.difference_update(disconnected)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, request: Request):
    """Accept client, register event handlers, handle ping/pong."""
    await websocket.accept()
    _clients.add(websocket)
    ctx = request.app.state.ctx

    # Register broadcast handlers for all forwarded events
    for event in _FORWARDED_EVENTS:
        ctx.emitter.on(
            event,
            lambda payload, e=event: asyncio.create_task(broadcast(e, payload)),
        )

    log.info("ws_client_connected", total=len(_clients))
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        _clients.discard(websocket)
        log.info("ws_client_disconnected", total=len(_clients))

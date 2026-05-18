"""
websocket.py – WebSocket broadcast hub.

All engine events (fills, positions, signals) are forwarded to every
connected TradingView client in real-time.
"""
from __future__ import annotations

import asyncio
import json
from typing import Set

import structlog
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

log = structlog.get_logger(__name__)
router = APIRouter()

# Set of all active WebSocket connections
_clients: Set[WebSocket] = set()


async def broadcast(event: str, payload: dict) -> None:
    """Push a JSON event to all connected clients. Drops dead connections."""
    message = json.dumps({"event": event, "payload": payload}, default=str)
    dead: Set[WebSocket] = set()
    for ws in _clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)
    if dead:
        log.debug("ws_dropped_dead_clients", count=len(dead))


# Events emitted by the engines that TradingView needs to react to
_SUBSCRIBED_EVENTS = [
    "signal_created",
    "signal_rejected",
    "order_filled",
    "position_opened",
    "position_update_required",
    "trade_closed",
    "partial_close",
    "tp_hit",
    "sl_hit",
    "risk_veto",
    "daily_loss_limit",
    "drawdown_limit",
    "emergency_stop",
]


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, request: Request):
    """Accept a WebSocket client and subscribe it to all engine events."""
    await websocket.accept()
    _clients.add(websocket)
    ctx = request.app.state.ctx

    # Register broadcast handlers on the shared EventEmitter
    for event in _SUBSCRIBED_EVENTS:
        # Capture event name in closure
        def make_handler(ev: str):
            def handler(payload: dict):
                asyncio.create_task(broadcast(ev, payload))
            return handler
        ctx.emitter.on(event, make_handler(event))

    log.info("ws_client_connected", total=len(_clients))

    try:
        while True:
            # Keep-alive: respond to ping frames
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        _clients.discard(websocket)
        log.info("ws_client_disconnected", remaining=len(_clients))

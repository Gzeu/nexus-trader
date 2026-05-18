"""
websocket.py – WebSocket endpoint for live updates to TradingView UI.
"""
from __future__ import annotations

import asyncio
import json
from typing import Set

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request

log = structlog.get_logger(__name__)
router = APIRouter()

_clients: Set[WebSocket] = set()


async def broadcast(event: str, payload: dict) -> None:
    message = json.dumps({"event": event, "payload": payload})
    disconnected = set()
    for ws in _clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    _clients.difference_update(disconnected)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, request: Request):
    await websocket.accept()
    _clients.add(websocket)
    ctx = request.app.state.ctx

    for event in [
        "signal_created", "signal_rejected", "order_filled",
        "position_opened", "trade_closed", "partial_close",
        "tp_hit", "sl_hit", "position_update_required",
    ]:
        ctx.emitter.on(event, lambda payload, e=event: asyncio.create_task(broadcast(e, payload)))

    log.info("ws_client_connected", total=len(_clients))
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        _clients.discard(websocket)
        log.info("ws_client_disconnected", total=len(_clients))

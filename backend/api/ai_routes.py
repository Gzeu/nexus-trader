"""
ai_routes.py — AI Copilot endpoints.

Endpoints:
  POST /api/v1/ai/chat         — Chat non-streaming (JSON response)
  POST /api/v1/ai/chat/stream  — Chat streaming (SSE)
  POST /api/v1/ai/execute      — Executa o actiune propusa dupa confirmare
  GET  /api/v1/ai/status       — Verifica daca AI e configurat si activ

Provider priority: Groq (gratuit, rapid) -> OpenAI fallback
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.ai_context import ASST_SYSTEM_PROMPT, build_context
from backend.api.state import AppState, get_state
from backend.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


# ─── Pydantic models ──────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    stream: bool = False


class ExecuteActionRequest(BaseModel):
    action_type: str
    params: Dict[str, Any] = {}


# ─── LLM client helper ────────────────────────────────────────────────────────

async def _call_groq(
    messages: List[Dict], stream: bool = False
) -> Any:
    """Apeleaza Groq API (llama-3.3-70b-versatile)."""
    try:
        from groq import AsyncGroq  # type: ignore
    except ImportError:
        raise HTTPException(status_code=503, detail="groq package not installed. Run: pip install groq")

    cfg = get_settings()
    if not cfg.groq_api_key:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY not configured")

    client = AsyncGroq(api_key=cfg.groq_api_key)
    return await client.chat.completions.create(
        model=cfg.ai_model or "llama-3.3-70b-versatile",
        messages=messages,
        stream=stream,
        max_tokens=1024,
        temperature=0.3,
    )


async def _call_openai(
    messages: List[Dict], stream: bool = False
) -> Any:
    """Fallback catre OpenAI daca Groq nu e disponibil."""
    try:
        from openai import AsyncOpenAI  # type: ignore
    except ImportError:
        raise HTTPException(status_code=503, detail="openai package not installed. Run: pip install openai")

    cfg = get_settings()
    if not cfg.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")

    client = AsyncOpenAI(api_key=cfg.openai_api_key)
    return await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        stream=stream,
        max_tokens=1024,
        temperature=0.3,
    )


async def _call_llm(messages: List[Dict], stream: bool = False) -> Any:
    """Groq first, fallback la OpenAI."""
    cfg = get_settings()
    if cfg.groq_api_key:
        try:
            return await _call_groq(messages, stream=stream)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Groq failed (%s), falling back to OpenAI", exc)
    # Fallback OpenAI
    return await _call_openai(messages, stream=stream)


# ─── Status ───────────────────────────────────────────────────────────────────

@router.get("/status")
async def ai_status() -> Dict[str, Any]:
    cfg = get_settings()
    has_groq = bool(cfg.groq_api_key)
    has_openai = bool(cfg.openai_api_key)
    return {
        "enabled": cfg.ai_enabled,
        "provider": "groq" if has_groq else ("openai" if has_openai else "none"),
        "model": cfg.ai_model or "llama-3.3-70b-versatile",
        "has_groq": has_groq,
        "has_openai": has_openai,
    }


# ─── Chat (non-streaming) ─────────────────────────────────────────────────────

@router.post("/chat")
async def ai_chat(
    req: ChatRequest,
    state: AppState = Depends(get_state),
) -> Dict[str, Any]:
    cfg = get_settings()
    if not cfg.ai_enabled:
        raise HTTPException(status_code=503, detail="AI Copilot disabled. Set AI_ENABLED=true in .env")

    context_json = await build_context(state)
    system_msg = {
        "role": "system",
        "content": f"{ASST_SYSTEM_PROMPT}\n\n## DATE LIVE CONT\n```json\n{context_json}\n```",
    }
    messages = [system_msg] + [m.model_dump() for m in req.messages]

    response = await _call_llm(messages, stream=False)
    content = response.choices[0].message.content

    return {
        "content": content,
        "model": response.model,
        "usage": {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
        } if response.usage else {},
    }


# ─── Chat streaming (SSE) ─────────────────────────────────────────────────────

@router.post("/chat/stream")
async def ai_chat_stream(
    req: ChatRequest,
    state: AppState = Depends(get_state),
):
    cfg = get_settings()
    if not cfg.ai_enabled:
        raise HTTPException(status_code=503, detail="AI Copilot disabled. Set AI_ENABLED=true in .env")

    context_json = await build_context(state)
    system_msg = {
        "role": "system",
        "content": f"{ASST_SYSTEM_PROMPT}\n\n## DATE LIVE CONT\n```json\n{context_json}\n```",
    }
    messages = [system_msg] + [m.model_dump() for m in req.messages]

    async def event_generator() -> AsyncIterator[str]:
        try:
            stream = await _call_llm(messages, stream=True)
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    data = json.dumps({"delta": delta.content})
                    yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except HTTPException as exc:
            yield f"data: {json.dumps({'error': exc.detail})}\n\n"
        except Exception as exc:
            logger.error("AI stream error: %s", exc)
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Execute action (dupa confirmare UI) ─────────────────────────────────────

@router.post("/execute")
async def ai_execute(
    req: ExecuteActionRequest,
    state: AppState = Depends(get_state),
) -> Dict[str, Any]:
    """
    Executa o actiune propusa de AI dupa confirmarea explicita a traderului.
    Aceasta este singura cale prin care AI poate declansa actiuni reale.
    """
    cfg = get_settings()
    if not cfg.ai_enabled:
        raise HTTPException(status_code=503, detail="AI Copilot disabled")

    action = req.action_type
    params = req.params
    logger.info("AI execute: action=%s params=%s", action, params)

    # ── place_order ────────────────────────────────────────────────────────────
    if action == "place_order":
        if not state.portfolio.is_ready:
            raise HTTPException(status_code=503, detail="System not reconciled")
        if state.risk.is_paused:
            raise HTTPException(status_code=503, detail="Risk manager paused")
        try:
            result = await state.execution.place_order(
                symbol=params["symbol"],
                side=params["side"],
                quantity=float(params["quantity"]),
                order_type=params.get("order_type", "MARKET"),
                price=params.get("price"),
                stop_loss=params.get("stop_loss"),
                take_profit=params.get("take_profit"),
            )
            await state.telegram.send_alert(
                f"🤖 AI Order: {params['side']} {params['quantity']} {params['symbol']}"
            )
            return {"success": True, "action": action, "result": result}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── close_position ─────────────────────────────────────────────────────────
    elif action == "close_position":
        symbol = params.get("symbol")
        if not symbol:
            raise HTTPException(status_code=422, detail="symbol required")
        positions = state.portfolio.get_positions()
        pos = next((p for p in positions if p.symbol == symbol), None)
        if not pos:
            raise HTTPException(status_code=404, detail=f"No open position for {symbol}")
        try:
            close_side = "SELL" if pos.side == "BUY" else "BUY"
            await state.client.place_market_order(symbol, close_side, pos.quantity)
            state.portfolio.remove_position(symbol)
            return {"success": True, "action": action, "symbol": symbol}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── emergency_stop ─────────────────────────────────────────────────────────
    elif action == "emergency_stop":
        state.risk.pause(reason="AI Copilot — confirmat de trader")
        await state.automation.stop()
        await state.telegram.send_alert("🤖 AI: Emergency stop activat de trader via AI Copilot")
        return {"success": True, "action": action}

    # ── resume_trading ─────────────────────────────────────────────────────────
    elif action == "resume_trading":
        state.risk.resume()
        await state.automation.start()
        await state.telegram.send_alert("🤖 AI: Trading reluat de trader via AI Copilot")
        return {"success": True, "action": action}

    # ── cancel_all ─────────────────────────────────────────────────────────────
    elif action == "cancel_all":
        symbol = params.get("symbol")
        try:
            symbols = [symbol] if symbol else [p.symbol for p in state.portfolio.get_positions()]
            for sym in symbols:
                await state.client.cancel_all_orders(sym)
            return {"success": True, "action": action, "symbols": symbols}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── close_all ──────────────────────────────────────────────────────────────
    elif action == "close_all":
        if not state.portfolio.is_ready:
            raise HTTPException(status_code=503, detail="Not reconciled")
        positions = state.portfolio.get_positions()
        closed, errors = [], []
        for pos in positions:
            try:
                side = "SELL" if pos.side == "BUY" else "BUY"
                await state.client.place_market_order(pos.symbol, side, pos.quantity)
                state.portfolio.remove_position(pos.symbol)
                closed.append(pos.symbol)
            except Exception as exc:
                errors.append({"symbol": pos.symbol, "error": str(exc)})
        return {"success": True, "action": action, "closed": closed, "errors": errors}

    # ── patch_settings ─────────────────────────────────────────────────────────
    elif action == "patch_settings":
        data = params.get("data", {})
        if not data:
            raise HTTPException(status_code=422, detail="data dict required")
        # Reutilizam logica din routes.py (import inline pentru a evita circular)
        from backend.api.routes import _settings_overrides, _SENSITIVE_KEYS
        applied = {}
        cfg2 = get_settings()
        for key, value in data.items():
            if key in _SENSITIVE_KEYS:
                continue
            if hasattr(cfg2, key):
                _settings_overrides[key] = value
                applied[key] = value
        return {"success": True, "action": action, "applied": applied}

    else:
        raise HTTPException(status_code=422, detail=f"Unknown action type: {action}")

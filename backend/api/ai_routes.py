"""
ai_routes.py — AI Copilot endpoints.

Endpoints:
  POST /api/v1/ai/chat      → Trimite mesaj, primește răspuns streamat (SSE)
  GET  /api/v1/ai/status    → Verifică dacă AI e activat și ce provider e folosit

Provider logic:
  1. Dacă groq_api_key e setat → Groq (llama-3.3-70b-versatile) — gratuit, rapid
  2. Fallback la OpenAI (gpt-4o-mini) dacă openai_api_key e setat
  3. Dacă niciunul → 503

Streaming: Server-Sent Events (text/event-stream) — fiecare chunk e un token.
Frontend (useAI.ts) consumă stream-ul via fetch() + ReadableStream.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.ai_context import build_system_prompt
from backend.api.state import AppState, get_state
from backend.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


# ─── Request / Response models ────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    include_context: bool = True  # injectează date live în system prompt


# ─── Provider helpers ─────────────────────────────────────────────────────────

def _get_provider() -> tuple[str, str, str]:
    """
    Returnează (provider_name, api_key, model_name) pe baza config.
    Ridică HTTPException 503 dacă AI nu e activat sau nu există API key.
    """
    cfg = get_settings()

    if not cfg.ai_enabled:
        raise HTTPException(
            status_code=503,
            detail="AI Copilot dezactivat. Setează AI_ENABLED=true în .env.",
        )

    # Groq preferred
    if cfg.groq_api_key:
        model = cfg.ai_model or "llama-3.3-70b-versatile"
        return "groq", cfg.groq_api_key, model

    # Fallback OpenAI
    if cfg.openai_api_key:
        model = cfg.ai_model or "gpt-4o-mini"
        return "openai", cfg.openai_api_key, model

    raise HTTPException(
        status_code=503,
        detail=(
            "Niciun API key AI configurat. "
            "Setează GROQ_API_KEY (recomandat, gratuit) sau OPENAI_API_KEY în .env, "
            "apoi AI_ENABLED=true."
        ),
    )


async def _stream_groq(
    api_key: str,
    model: str,
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Streaming SSE via Groq REST API (fără SDK — httpx async)."""
    try:
        import httpx
    except ImportError:
        yield _sse_error("httpx nu e instalat. Rulează: pip install httpx")
        return

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.4,
        "max_tokens": 1024,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                yield _sse_error(f"Groq error {resp.status_code}: {body.decode()[:200]}")
                return

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    yield "data: [DONE]\n\n"
                    return
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield f"data: {json.dumps({'token': delta})}\n\n"
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


async def _stream_openai(
    api_key: str,
    model: str,
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Streaming SSE via OpenAI REST API (fără SDK — httpx async)."""
    try:
        import httpx
    except ImportError:
        yield _sse_error("httpx nu e instalat. Rulează: pip install httpx")
        return

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.4,
        "max_tokens": 1024,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                yield _sse_error(f"OpenAI error {resp.status_code}: {body.decode()[:200]}")
                return

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    yield "data: [DONE]\n\n"
                    return
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield f"data: {json.dumps({'token': delta})}\n\n"
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


def _sse_error(msg: str) -> str:
    return f"data: {json.dumps({'error': msg})}\n\n"


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/status")
async def ai_status() -> Dict[str, Any]:
    """
    Returnează starea AI Copilot: activat, provider, model.
    Folosit de frontend pentru a afișa/ascunde butonul AI.
    """
    cfg = get_settings()

    if not cfg.ai_enabled:
        return {"enabled": False, "provider": None, "model": None}

    if cfg.groq_api_key:
        model = cfg.ai_model or "llama-3.3-70b-versatile"
        return {"enabled": True, "provider": "groq", "model": model}

    if cfg.openai_api_key:
        model = cfg.ai_model or "gpt-4o-mini"
        return {"enabled": True, "provider": "openai", "model": model}

    return {
        "enabled": False,
        "provider": None,
        "model": None,
        "warning": "AI_ENABLED=true dar niciun API key configurat.",
    }


@router.post("/chat")
async def ai_chat(
    req: ChatRequest,
    state: AppState = Depends(get_state),
) -> StreamingResponse:
    """
    Primește un mesaj de la user și returnează răspunsul AI streamat (SSE).

    Flow:
      1. Verifică provider + API key
      2. Construiește system prompt cu date live din AppState (dacă include_context=True)
      3. Asamblează lista de mesaje (system + history + mesaj curent)
      4. Streamează răspunsul LLM ca Server-Sent Events

    SSE format per chunk:
      data: {"token": "...text fragment..."}\n\n
    SSE final:
      data: [DONE]\n\n
    SSE eroare:
      data: {"error": "...mesaj eroare..."}\n\n
    """
    provider, api_key, model = _get_provider()

    # 1. System prompt cu context live
    if req.include_context:
        system_content = await build_system_prompt(state)
    else:
        system_content = (
            "Ești NexusTrader AI Copilot, un asistent expert în trading automatizat "
            "pe Binance (Spot + Futures). Răspunzi concis și precis."
        )

    # 2. Asamblare mesaje
    messages: list[dict] = [{"role": "system", "content": system_content}]
    for msg in req.history[-10:]:  # maxim 10 mesaje anterioare în context
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": req.message})

    logger.info(
        "ai_chat: provider=%s model=%s history_len=%d message_len=%d",
        provider, model, len(req.history), len(req.message),
    )

    # 3. Stream
    if provider == "groq":
        stream = _stream_groq(api_key, model, messages)
    else:
        stream = _stream_openai(api_key, model, messages)

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # dezactivează buffering nginx
        },
    )

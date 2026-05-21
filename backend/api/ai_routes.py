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

Rate-limit handling (I3):
  _stream_groq_with_retry() wraps _stream_groq() și la HTTP 429:
    - Citeste Retry-After header (fallback 10s)
    - await asyncio.sleep() cu cap la 60s
    - Retry maxim MAX_RETRIES=3 ori
    - La a 4-a eroare: SSE error + fallback la OpenAI dacă există key
"""
from __future__ import annotations

import asyncio
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

MAX_RETRIES = 3          # număr maxim retry la 429
_RETRY_CAP_S = 60.0      # sleep maxim per retry (secunde)
_RETRY_DEFAULT_S = 10.0  # fallback dacă Retry-After header lipsește


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


# ─── Core streaming helpers ───────────────────────────────────────────────────

async def _stream_groq(
    api_key: str,
    model: str,
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Streaming SSE via Groq REST API (fără SDK — httpx async).

    Yields:
      - SSE token chunks: ``data: {"token": "..."}""
      - SSE done marker: ``data: [DONE]""
      - SSE error (non-retryable): ``data: {"error": "..."}""
      - SSE rate-limit sentinel (retryable): ``data: {"_rate_limit": {"retry_after": N}}""
        → consumat de _stream_groq_with_retry(), nu ajunge la frontend.
    """
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
            if resp.status_code == 429:
                # Citim header Retry-After (poate fi float sau int în secunde)
                retry_after_raw = resp.headers.get("retry-after", str(_RETRY_DEFAULT_S))
                try:
                    retry_after = float(retry_after_raw)
                except ValueError:
                    retry_after = _RETRY_DEFAULT_S
                retry_after = min(retry_after, _RETRY_CAP_S)

                # Citim body pentru logging detaliat
                body = await resp.aread()
                logger.warning(
                    "_stream_groq: 429 rate-limit — Retry-After=%.1fs — body=%s",
                    retry_after, body.decode()[:200],
                )
                # Sentinel intern — va fi interceptat de _stream_groq_with_retry
                yield f"data: {json.dumps({'_rate_limit': {'retry_after': retry_after}})}\n\n"
                return

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


async def _stream_groq_with_retry(
    api_key: str,
    model: str,
    messages: list[dict],
    openai_key: Optional[str] = None,
    openai_model: str = "gpt-4o-mini",
) -> AsyncGenerator[str, None]:
    """
    Wrapper cu retry automat la 429 pentru _stream_groq.

    Logică:
      1. Apelează _stream_groq și consumă stream-ul token cu token.
      2. Dacă întâlnește sentinela _rate_limit:
         a. Trimite SSE {"notice": "Rate limit Groq, reîncerc în Xs..."} la frontend
         b. await asyncio.sleep(retry_after)
         c. Încearcă din nou — maxim MAX_RETRIES ori
      3. La epuizarea retry-urilor:
         a. Dacă există openai_key → trimite SSE notice de fallback + streamează OpenAI
         b. Altfel → SSE error final
    """
    attempt = 0

    while attempt <= MAX_RETRIES:
        collected: list[str] = []  # buffer chunks înainte de a decide
        rate_limited = False
        retry_after = _RETRY_DEFAULT_S

        async for chunk in _stream_groq(api_key, model, messages):
            # Detecție sentinel intern
            if chunk.startswith("data: ") and '"_rate_limit"' in chunk:
                try:
                    payload = json.loads(chunk[6:])
                    retry_after = payload["_rate_limit"]["retry_after"]
                except (json.JSONDecodeError, KeyError):
                    pass
                rate_limited = True
                break  # nu yieldăm sentinela la frontend

            collected.append(chunk)

        if not rate_limited:
            # Stream complet fără rate-limit — yieldăm tot ce am colectat
            for c in collected:
                yield c
            return

        # Rate limited
        attempt += 1
        logger.warning(
            "_stream_groq_with_retry: rate-limit attempt %d/%d, sleep %.1fs",
            attempt, MAX_RETRIES, retry_after,
        )

        if attempt <= MAX_RETRIES:
            # Notificăm frontend că așteptăm (non-blocking UX)
            yield f"data: {json.dumps({'notice': f'Rate limit Groq, reîncerc în {retry_after:.0f}s... (încercare {attempt}/{MAX_RETRIES})'})}\n\n"
            await asyncio.sleep(retry_after)
            continue

        # Epuizat retry-uri
        if openai_key:
            logger.warning(
                "_stream_groq_with_retry: toate %d retry-uri epuizate — fallback la OpenAI",
                MAX_RETRIES,
            )
            yield f"data: {json.dumps({'notice': 'Groq rate-limit epuizat — comut la OpenAI...'})}\n\n"
            async for chunk in _stream_openai(openai_key, openai_model, messages):
                yield chunk
        else:
            yield _sse_error(
                f"Rate limit Groq — toate {MAX_RETRIES} retry-uri epuizate și nu există "
                "fallback OpenAI. Setează OPENAI_API_KEY sau așteaptă și reîncearcă."
            )
        return


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
         - Groq: prin _stream_groq_with_retry() cu retry automat la 429
         - OpenAI: direct prin _stream_openai()

    SSE format per chunk:
      data: {"token": "...text fragment..."}\n\n
    SSE notice (retry/fallback info):
      data: {"notice": "..."}\n\n
    SSE final:
      data: [DONE]\n\n
    SSE eroare:
      data: {"error": "...mesaj eroare..."}\n\n
    """
    provider, api_key, model = _get_provider()
    cfg = get_settings()

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

    # 3. Stream — Groq cu retry 429, OpenAI direct
    if provider == "groq":
        # Pasăm openai_key pentru fallback la epuizarea retry-urilor
        openai_key: Optional[str] = cfg.openai_api_key if cfg.openai_api_key else None
        openai_model = cfg.ai_model or "gpt-4o-mini" if openai_key else "gpt-4o-mini"
        stream = _stream_groq_with_retry(
            api_key, model, messages,
            openai_key=openai_key,
            openai_model=openai_model,
        )
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

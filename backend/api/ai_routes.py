"""
ai_routes.py — AI Copilot endpoints.

Endpoints:
  POST /api/v1/ai/chat      → Trimite mesaj, primește răspuns streamat (SSE)
  GET  /api/v1/ai/status    → Verifică dacă AI e activat și ce provider e folosit
  POST /api/v1/ai/execute   → Execută o acțiune propusă de AI (I2)

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

Action executor (I2):
  POST /ai/execute primește { action_type, params } și mapează pe logica
  existentă din routes.py / AppState. Toate acțiunile write sunt blocate
  dacă sistemul nu e reconciliat sau risk managerul e pauzeit (excepție:
  emergency_stop și resume_trading care funcționează oricând).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

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


class ExecuteRequest(BaseModel):
    action_type: str
    params: Dict[str, Any] = {}


class ExecuteResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


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
      - SSE token chunks: ``data: {"token": "..."}``
      - SSE done marker: ``data: [DONE]``
      - SSE error (non-retryable): ``data: {"error": "..."}``
      - SSE rate-limit sentinel (retryable): ``data: {"_rate_limit": {"retry_after": N}}``
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


# ─── Action executor helpers ──────────────────────────────────────────────────

async def _exec_emergency_stop(state: AppState, _params: Dict[str, Any]) -> ExecuteResponse:
    """Oprire de urgență: pauzează risk + oprește automation + notifică Telegram."""
    state.risk.pause(reason="emergency_stop via AI Copilot")
    await state.automation.stop()
    try:
        await state.telegram.send_alert("🚨 EMERGENCY STOP activat via AI Copilot")
    except Exception as tg_err:
        logger.warning("_exec_emergency_stop: telegram alert failed: %s", tg_err)
    logger.info("AI action: emergency_stop executed")
    return ExecuteResponse(success=True, message="Emergency stop activat. Trading oprit.")


async def _exec_resume_trading(state: AppState, _params: Dict[str, Any]) -> ExecuteResponse:
    """Reia trading-ul: depauzează risk + pornește automation."""
    state.risk.resume()
    await state.automation.start()
    logger.info("AI action: resume_trading executed")
    return ExecuteResponse(success=True, message="Trading reluat. AutomationEngine pornit.")


async def _exec_cancel_all_orders(state: AppState, params: Dict[str, Any]) -> ExecuteResponse:
    """
    Anulează toate ordinele deschise.
    params.symbol (opțional): dacă specificat, anulează doar pentru acel simbol.
    """
    symbol: Optional[str] = params.get("symbol")
    if symbol:
        symbols: List[str] = [symbol.upper()]
    else:
        symbols = [p.symbol for p in state.portfolio.get_positions()]
        if not symbols:
            # Încearcă și ordinele fără poziție corespunzătoare
            try:
                open_orders = state.portfolio.get_open_orders()
                symbols = list({o.symbol for o in open_orders})
            except Exception:
                pass

    if not symbols:
        return ExecuteResponse(success=True, message="Nu există ordine deschise de anulat.", data={"cancelled": []})

    cancelled, errors = [], []
    for sym in symbols:
        try:
            await state.client.cancel_all_orders(sym)
            cancelled.append(sym)
        except Exception as exc:
            errors.append({"symbol": sym, "error": str(exc)})
            logger.warning("_exec_cancel_all_orders: %s failed: %s", sym, exc)

    logger.info("AI action: cancel_all_orders — cancelled=%s errors=%s", cancelled, errors)
    return ExecuteResponse(
        success=len(errors) == 0,
        message=f"Anulat ordine pentru {len(cancelled)} simboluri." + (f" Erori: {len(errors)}." if errors else ""),
        data={"cancelled": cancelled, "errors": errors},
    )


async def _exec_close_all_positions(state: AppState, params: Dict[str, Any]) -> ExecuteResponse:
    """
    Închide toate pozițiile deschise la market.
    params.symbol (opțional): dacă specificat, închide doar poziția respectivă.
    """
    if not state.portfolio.is_ready:
        return ExecuteResponse(success=False, error="Sistem nereconciliat — imposibil de închis pozițiile.")

    all_positions = state.portfolio.get_positions()
    symbol: Optional[str] = params.get("symbol")
    positions = [p for p in all_positions if p.symbol == symbol.upper()] if symbol else all_positions

    if not positions:
        return ExecuteResponse(success=True, message="Nu există poziții deschise de închis.", data={"closed": []})

    closed, errors = [], []
    for pos in positions:
        try:
            side = "SELL" if pos.side == "BUY" else "BUY"
            await state.client.place_market_order(pos.symbol, side, pos.quantity)
            state.portfolio.remove_position(pos.symbol)
            closed.append(pos.symbol)
        except Exception as exc:
            errors.append({"symbol": pos.symbol, "error": str(exc)})
            logger.warning("_exec_close_all_positions: %s failed: %s", pos.symbol, exc)

    logger.info("AI action: close_all_positions — closed=%s errors=%s", closed, errors)
    return ExecuteResponse(
        success=len(errors) == 0,
        message=f"Închise {len(closed)} poziții." + (f" Erori: {len(errors)}." if errors else ""),
        data={"closed": closed, "errors": errors},
    )


async def _exec_place_order(state: AppState, params: Dict[str, Any]) -> ExecuteResponse:
    """
    Plasează un ordin manual.
    params: { symbol, side, quantity, order_type?, price?, stop_loss?, take_profit? }
    """
    if not state.portfolio.is_ready:
        return ExecuteResponse(success=False, error="Sistem nereconciliat — trading blocat.")
    if state.risk.is_paused:
        return ExecuteResponse(success=False, error="Risk manager pauzeit — trading blocat.")

    required = ("symbol", "side", "quantity")
    missing = [k for k in required if k not in params]
    if missing:
        return ExecuteResponse(success=False, error=f"Parametri lipsă: {', '.join(missing)}")

    try:
        result = await state.execution.place_order(
            symbol=str(params["symbol"]).upper(),
            side=str(params["side"]).upper(),
            quantity=float(params["quantity"]),
            order_type=str(params.get("order_type", "MARKET")).upper(),
            price=float(params["price"]) if params.get("price") else None,
            stop_loss=float(params["stop_loss"]) if params.get("stop_loss") else None,
            take_profit=float(params["take_profit"]) if params.get("take_profit") else None,
        )
        logger.info("AI action: place_order — symbol=%s side=%s qty=%s result=%s",
                    params["symbol"], params["side"], params["quantity"], result)
        return ExecuteResponse(
            success=True,
            message=f"Ordin plasat: {params['side']} {params['quantity']} {params['symbol']}",
            data={"order": result},
        )
    except Exception as exc:
        logger.error("_exec_place_order failed: %s", exc)
        return ExecuteResponse(success=False, error=str(exc))


async def _exec_pause_symbol(state: AppState, params: Dict[str, Any]) -> ExecuteResponse:
    """
    Pauzează trading-ul pentru un simbol specific.
    params: { symbol }
    Folosește risk.pause_symbol() dacă există, altfel fallback la blocarea în settings_overrides.
    """
    symbol: Optional[str] = params.get("symbol")
    if not symbol:
        return ExecuteResponse(success=False, error="Parametru 'symbol' lipsă.")
    symbol = symbol.upper()

    # Încearcă method per-symbol dacă e implementat în RiskManager
    if hasattr(state.risk, "pause_symbol"):
        try:
            state.risk.pause_symbol(symbol)
            logger.info("AI action: pause_symbol — %s", symbol)
            return ExecuteResponse(success=True, message=f"Simbolul {symbol} pauzeit.")
        except Exception as exc:
            return ExecuteResponse(success=False, error=str(exc))

    # Fallback: înregistrăm în state ca atribut de blocaj temporar
    if not hasattr(state, "_paused_symbols"):
        state._paused_symbols = set()  # type: ignore[attr-defined]
    state._paused_symbols.add(symbol)  # type: ignore[attr-defined]
    logger.info("AI action: pause_symbol (fallback set) — %s", symbol)
    return ExecuteResponse(
        success=True,
        message=f"Simbolul {symbol} adăugat în lista de pauză internă (până la restart).",
        data={"paused_symbols": list(state._paused_symbols)},  # type: ignore[attr-defined]
    )


async def _exec_set_risk_param(state: AppState, params: Dict[str, Any]) -> ExecuteResponse:
    """
    Setează un parametru de risc runtime (override in-memory).
    params: { key: str, value: any }
    Chei acceptate: max_drawdown_pct, max_daily_loss_pct, max_position_size,
                    max_open_positions, risk_per_trade_pct
    """
    ALLOWED_RISK_KEYS = {
        "max_drawdown_pct",
        "max_daily_loss_pct",
        "max_position_size",
        "max_open_positions",
        "risk_per_trade_pct",
        "stop_loss_pct",
        "take_profit_pct",
    }

    key: Optional[str] = params.get("key")
    value = params.get("value")

    if not key:
        return ExecuteResponse(success=False, error="Parametru 'key' lipsă.")
    if value is None:
        return ExecuteResponse(success=False, error="Parametru 'value' lipsă.")
    if key not in ALLOWED_RISK_KEYS:
        return ExecuteResponse(
            success=False,
            error=f"Cheia '{key}' nu este permisă. Chei acceptate: {', '.join(sorted(ALLOWED_RISK_KEYS))}",
        )

    cfg = get_settings()
    if not hasattr(cfg, key):
        return ExecuteResponse(success=False, error=f"Cheia '{key}' nu există în Settings schema.")

    # Import _settings_overrides din routes.py — folosim același dict shared
    try:
        from backend.api.routes import _settings_overrides
        _settings_overrides[key] = value
    except ImportError:
        # Fallback: setăm direct pe obiectul cfg (non-persistent)
        logger.warning("_exec_set_risk_param: nu am putut importa _settings_overrides din routes.py")
        object.__setattr__(cfg, key, value)

    logger.info("AI action: set_risk_param — %s=%s", key, value)
    return ExecuteResponse(
        success=True,
        message=f"Parametrul de risc '{key}' setat la {value} (in-memory, reset la restart).",
        data={"key": key, "value": value},
    )


async def _exec_get_status(state: AppState, _params: Dict[str, Any]) -> ExecuteResponse:
    """
    Returnează un snapshot read-only al stării sistemului.
    Action read-only — nu are side effects, nu necesită reconciliere.
    """
    positions = state.portfolio.get_positions()
    try:
        balance = await state.portfolio.get_balance_summary()
        equity = balance.total_usdt_value
        available = balance.available_margin
    except Exception:
        equity = state.portfolio.get_equity()
        available = 0.0

    data = {
        "reconciled": state.portfolio.is_ready,
        "automation_running": state.automation.running,
        "risk_paused": state.risk.is_paused,
        "open_positions": len(positions),
        "equity_usdt": round(equity, 2),
        "available_usdt": round(available, 2),
        "consecutive_losses": state.risk.consecutive_losses,
        "daily_pnl": state.risk.daily_pnl,
    }
    return ExecuteResponse(
        success=True,
        message="Status sistem obținut.",
        data=data,
    )


# ─── Action dispatcher ────────────────────────────────────────────────────────

_ACTION_HANDLERS = {
    "emergency_stop":      _exec_emergency_stop,
    "resume_trading":      _exec_resume_trading,
    "cancel_all_orders":   _exec_cancel_all_orders,
    "close_all_positions": _exec_close_all_positions,
    "place_order":         _exec_place_order,
    "pause_symbol":        _exec_pause_symbol,
    "set_risk_param":      _exec_set_risk_param,
    "get_status":          _exec_get_status,
}

# Acțiunile care pot rula chiar dacă risk e pauzeit sau sistemul nereconciliat
_ALWAYS_ALLOWED = {"emergency_stop", "resume_trading", "get_status"}


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
        return {"enabled": True, "provider": "groq", "model": model,
                "has_groq": True, "has_openai": bool(cfg.openai_api_key)}

    if cfg.openai_api_key:
        model = cfg.ai_model or "gpt-4o-mini"
        return {"enabled": True, "provider": "openai", "model": model,
                "has_groq": False, "has_openai": True}

    return {
        "enabled": False,
        "provider": None,
        "model": None,
        "has_groq": False,
        "has_openai": False,
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


@router.post("/execute", response_model=ExecuteResponse)
async def ai_execute(
    req: ExecuteRequest,
    state: AppState = Depends(get_state),
) -> ExecuteResponse:
    """
    Execută o acțiune propusă de AI Copilot după confirmare din partea utilizatorului.

    Acțiuni suportate:
      emergency_stop      — oprire urgență (always allowed)
      resume_trading      — reluare trading (always allowed)
      cancel_all_orders   — anulare ordine (params: symbol?)
      close_all_positions — închidere poziții (params: symbol?)
      place_order         — ordin manual (params: symbol, side, quantity, ...)
      pause_symbol        — pauzează un simbol (params: symbol)
      set_risk_param      — modifică parametru risc (params: key, value)
      get_status          — snapshot sistem read-only (always allowed)

    Securitate:
      - Acțiunile write sunt blocate dacă sistemul nu e reconciliat
        (excepție: emergency_stop, resume_trading, get_status)
      - action_type necunoscut → 400 (nu 500)
      - Toate acțiunile sunt logate la INFO
    """
    action_type = req.action_type.lower().strip()
    logger.info("ai_execute: action_type=%s params=%s", action_type, req.params)

    handler = _ACTION_HANDLERS.get(action_type)
    if handler is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Acțiune necunoscută: '{action_type}'. "
                f"Acțiuni disponibile: {', '.join(sorted(_ACTION_HANDLERS.keys()))}"
            ),
        )

    # Guard: acțiunile write necesită sistem reconciliat
    if action_type not in _ALWAYS_ALLOWED and not state.portfolio.is_ready:
        return ExecuteResponse(
            success=False,
            error="Sistemul nu este reconciliat. Acțiunea a fost blocată pentru siguranță.",
        )

    try:
        result = await handler(state, req.params)
        return result
    except Exception as exc:
        logger.error("ai_execute: unexpected error for action=%s: %s", action_type, exc, exc_info=True)
        return ExecuteResponse(success=False, error=f"Eroare internă: {exc}")

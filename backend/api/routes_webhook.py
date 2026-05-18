"""
routes_webhook.py – Receives Pine Script alerts from TradingView.

Endpoint: POST /api/v1/signals/webhook

Security:
- Validates `secret` field in payload against settings.API_SECRET_KEY
- Rate-limited by symbol (max 1 signal per candle_open_time, enforced in AutomationEngine)
- Dry-run and reconciliation checks applied before any order

Flow:
  TradingView Alert → Webhook → this endpoint → RiskManager.check_signal()
  → ExecutionEngine.place_market_order() → WebSocket broadcast → TradingView UI sync
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.models import (
    Action,
    EntryType,
    MarketMode,
    RiskVeto,
    SignalMetadata,
    StrategySignal,
    WSEventType,
)

log = structlog.get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/signals", tags=["Signals"])


class WebhookPayload(BaseModel):
    """JSON body sent by TradingView Pine Script alert."""
    secret: str
    symbol: str
    action: str  # "BUY" | "SELL" | "CLOSE"
    entry_type: str = "market"
    entry_price: Optional[float] = None
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    timeframe: str = "15m"
    market_mode: str = "SPOT"
    candle_open_time: Optional[int] = None
    reason: str = "TradingView webhook"


def _verify_secret(secret: str) -> None:
    if secret != settings.api_secret_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret",
        )


@router.post("/webhook", summary="Receive Pine Script alert from TradingView")
async def receive_webhook(payload: WebhookPayload, request: Request):
    """
    Validate, risk-check, and execute a signal received from TradingView Pine Script.

    Args:
        payload: Parsed JSON from TradingView alert webhook.
        request: FastAPI request (used to access app state).

    Returns:
        dict with status and order result.
    """
    _verify_secret(payload.secret)

    state = request.app.state
    if not state.portfolio.is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="System not reconciled yet. Trading blocked.",
        )

    # Build StrategySignal from webhook payload
    try:
        action = Action(payload.action.upper())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown action: {payload.action}",
        )

    signal = StrategySignal(
        symbol=payload.symbol.upper(),
        action=action,
        confidence=payload.confidence,
        entry_type=EntryType(payload.entry_type),
        entry_price=Decimal(str(payload.entry_price)) if payload.entry_price else None,
        stop_loss=Decimal(str(payload.stop_loss)),
        take_profit_1=Decimal(str(payload.take_profit_1)),
        take_profit_2=Decimal(str(payload.take_profit_2)),
        timeframe=payload.timeframe,
        reason=payload.reason,
        candle_open_time=payload.candle_open_time,
        metadata=SignalMetadata(strategy_name="tradingview_webhook"),
    )

    log.info(
        "webhook_signal_received",
        symbol=signal.symbol,
        action=str(signal.action),
        confidence=signal.confidence,
        candle_time=signal.candle_open_time,
    )

    # Anti-duplicate: check candle_open_time
    if signal.candle_open_time and state.automation._is_duplicate(
        signal.symbol, signal.candle_open_time
    ):
        log.info("webhook_duplicate_candle_skipped", symbol=signal.symbol)
        return {"status": "skipped", "reason": "duplicate_candle"}

    # Risk gate
    veto = state.risk.check_signal(signal)
    if veto != RiskVeto.OK:
        log.info("webhook_signal_rejected", veto=veto.value, symbol=signal.symbol)
        if state.ws_broadcast:
            await state.ws_broadcast(
                WSEventType.SIGNAL_REJECTED,
                {"symbol": signal.symbol, "reason": veto.value, "source": "webhook"},
            )
        return {"status": "rejected", "reason": veto.value}

    # Confidence filter
    if signal.confidence < settings.min_confidence:
        return {"status": "rejected", "reason": "low_confidence", "confidence": signal.confidence}

    # Position sizing
    from backend.core.trade_logic import calc_position_size
    equity = state.risk.equity
    price = float(signal.entry_price or 0)
    if price <= 0:
        return {"status": "rejected", "reason": "invalid_entry_price"}

    qty = calc_position_size(
        equity=equity,
        price=price,
        stop_loss=float(signal.stop_loss),
    )

    market_mode = MarketMode(payload.market_mode.upper())
    order = await state.execution.place_market_order(signal, qty, market_mode=market_mode)

    from backend.models import OrderStatus
    if order.status in (OrderStatus.FILLED, OrderStatus.DRY_RUN):
        state.automation._mark_processed(signal.symbol, signal.candle_open_time)
        if state.journal:
            await state.journal.log_signal(signal)
        if state.telegram:
            await state.telegram.alert_signal(signal)
        if state.ws_broadcast:
            await state.ws_broadcast(
                WSEventType.SIGNAL_CREATED,
                {"symbol": signal.symbol, "action": str(signal.action), "source": "webhook"},
            )

    return {
        "status": "ok",
        "dry_run": settings.dry_run,
        "order_status": str(order.status),
        "exchange_order_id": order.exchange_order_id,
        "symbol": signal.symbol,
        "qty": str(qty),
    }

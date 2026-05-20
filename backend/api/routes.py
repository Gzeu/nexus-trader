"""
FastAPI routes — toate endpoint-urile REST ale sistemului.
"/api/v1/" prefix aplicat in app.py.

FIX 3: place_order() construieste un OrderRequest real cu idempotency_key,
        in loc sa apeleze place_market_order() direct cu argumente incompatibile.
FIX 4: /signals elimina response_model — returneaza List[dict] fara validare Pydantic.
FIX 5: /metrics citeste drawdown din risk_manager.get_metrics() nu din getattr hack.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.api.state import AppState, get_state
from backend.config import get_settings
from backend.models import (
    Order,
    OrderRequest,
    OrderSide,
    OrderType,
    MarketMode,
    Position,
)
from backend.models_extra import AccountInfo, BalanceSummary

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────── health / status

@router.get("/health")
async def health(state: AppState = Depends(get_state)) -> Dict[str, Any]:
    cfg = get_settings()
    return {
        "status": "ok",
        "reconciled": state.portfolio.is_ready,
        "dry_run": cfg.dry_run,
        "testnet": cfg.testnet,
        "automation_running": state.automation.running,
    }


@router.get("/metrics")
async def metrics(state: AppState = Depends(get_state)) -> Dict[str, Any]:
    """
    Dashboard metrics: equity live din Binance + analytics + risk state.
    FIX 4+5: fetch live balance, drawdown din risk_manager.get_metrics().
    """
    # 1. Equity live
    try:
        balance        = await state.portfolio.get_balance_summary()
        total_equity   = balance.total_usdt_value
        available      = balance.available_margin
        unrealized_pnl = balance.unrealized_pnl
    except Exception as exc:
        logger.warning("metrics: balance fetch failed (%s), using cached", exc)
        total_equity   = state.portfolio.get_equity()
        available      = 0.0
        unrealized_pnl = 0.0

    # 2. Trade analytics
    rm = state.portfolio.get_risk_metrics()

    # 3. Risk state (FIX 5: din risk_manager.get_metrics(), nu getattr)
    risk_m = state.risk.get_metrics()

    return {
        "equity":          round(total_equity, 2),
        "available":       round(available, 2),
        "unrealized_pnl":  round(unrealized_pnl, 2),
        "realized_pnl":    round(rm.gross_profit - rm.gross_loss, 2),
        "win_rate":        rm.win_rate,
        "winning_trades":  rm.winning_trades,
        "losing_trades":   rm.losing_trades,
        "total_trades":    rm.total_trades,
        "profit_factor":   rm.profit_factor,
        "sharpe_ratio":    rm.sharpe_ratio,
        "expectancy":      rm.expectancy,
        "risk": {
            "paused":             risk_m.paused,
            "pause_reason":       risk_m.pause_reason,
            "consecutive_losses": risk_m.consecutive_losses,
            "daily_pnl":          round(risk_m.daily_pnl, 4),
            "daily_pnl_pct":      round(risk_m.daily_pnl_pct * 100, 2),
            "current_drawdown":   round(risk_m.current_drawdown * 100, 2),
            "max_drawdown_seen":  round(risk_m.max_drawdown * 100, 2),
            "peak_equity":        round(risk_m.peak_equity, 2),
        },
    }


# ─────────────────────────────────────────── account / balance

@router.get("/account", response_model=AccountInfo)
async def get_account(state: AppState = Depends(get_state)) -> AccountInfo:
    return await state.portfolio.get_account_info()


@router.get("/balance", response_model=BalanceSummary)
async def get_balance(state: AppState = Depends(get_state)) -> BalanceSummary:
    return await state.portfolio.get_balance_summary()


# ─────────────────────────────────────────── positions / orders

@router.get("/positions", response_model=List[Position])
async def get_positions(state: AppState = Depends(get_state)) -> List[Position]:
    return state.portfolio.get_positions()


@router.get("/orders", response_model=List[Order])
async def get_orders(state: AppState = Depends(get_state)) -> List[Order]:
    return state.portfolio.get_open_orders()


# ─────────────────────────────────────────── signals
# FIX 4: fara response_model — semnalele sunt List[dict] cu signal_status atasat.
# response_model=List[StrategySignal] facea Pydantic sa valideze si sa returneze []
# pentru orice semnal care avea campuri extra (signal_status, rejection_reason etc.)

@router.get("/signals")
async def get_signals(
    limit: int = Query(default=50, ge=1, le=200),
    state: AppState = Depends(get_state),
) -> List[Dict[str, Any]]:
    """Ultimele N semnale. Returneaza List[dict] cu toate campurile extra."""
    return state.automation.get_recent_signals(limit=limit)


# ─────────────────────────────────────────── manual order

class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str           # "BUY" | "SELL"
    quantity: float
    order_type: str = "MARKET"   # "MARKET" | "LIMIT"
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@router.post("/place_order")
async def place_order(
    req: PlaceOrderRequest,
    state: AppState = Depends(get_state),
) -> Dict[str, Any]:
    """
    Plaseaza un ordin manual (din TradingView sau UI direct).

    FIX 3: Construieste OrderRequest corect cu idempotency_key UUID,
    OrderSide/OrderType enum, Decimal quantity — in loc de a apela
    place_market_order(symbol, side, quantity) care nu exista pe ExecutionEngine.
    """
    if not state.portfolio.is_ready:
        raise HTTPException(status_code=503, detail="System not reconciled — trading blocked")
    if state.risk.is_paused:
        raise HTTPException(status_code=503, detail="Risk manager paused — trading blocked")

    try:
        side_enum  = OrderSide.BUY if req.side.upper() == "BUY" else OrderSide.SELL
        type_enum  = (
            OrderType.LIMIT if req.order_type.upper() == "LIMIT" else OrderType.MARKET
        )
        mode = (
            MarketMode.FUTURES
            if get_settings().futures_enabled
            else MarketMode.SPOT
        )

        order_req = OrderRequest(
            symbol=req.symbol,
            side=side_enum,
            order_type=type_enum,
            quantity=Decimal(str(req.quantity)),
            price=Decimal(str(req.price)) if req.price else None,
            market_mode=mode,
            idempotency_key=uuid4(),
        )

        order = await state.execution.place_order(order_req)

        # Daca avem SL/TP, plaseaza bracket in background
        if req.stop_loss and req.take_profit and order.status.value in ("FILLED", "DRY_RUN"):
            import asyncio
            asyncio.create_task(
                state.execution.bracket_order(
                    symbol=req.symbol,
                    side=side_enum,
                    quantity=Decimal(str(req.quantity)),
                    stop_loss=Decimal(str(req.stop_loss)),
                    take_profit=Decimal(str(req.take_profit)),
                    market_mode=mode,
                )
            )

        return {"success": True, "order": order.model_dump(mode="json")}
    except Exception as exc:
        logger.error("place_order failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────── journal

@router.get("/journal/trades")
async def journal_trades(
    symbol: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    state: AppState = Depends(get_state),
) -> Dict[str, Any]:
    trades = await state.journal.query_trades(symbol=symbol, limit=limit, offset=offset)
    return {"trades": trades, "count": len(trades)}


@router.get("/journal/signals")
async def journal_signals(
    symbol: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    state: AppState = Depends(get_state),
) -> Dict[str, Any]:
    signals = await state.journal.query_signals(symbol=symbol, limit=limit)
    return {"signals": signals, "count": len(signals)}


# ─────────────────────────────────────────── kill switches

@router.post("/emergency_stop")
async def emergency_stop(state: AppState = Depends(get_state)) -> Dict[str, str]:
    state.risk.pause(reason="emergency_stop via API")
    await state.automation.stop()
    await state.telegram.send_alert("🚨 EMERGENCY STOP activat via API")
    logger.critical("EMERGENCY STOP activated")
    return {"status": "emergency_stop_activated"}


@router.post("/resume_trading")
async def resume_trading(state: AppState = Depends(get_state)) -> Dict[str, str]:
    state.risk.resume()
    await state.automation.start()
    return {"status": "trading_resumed"}


@router.post("/cancel_all")
async def cancel_all(
    symbol: Optional[str] = Query(default=None),
    state: AppState = Depends(get_state),
) -> Dict[str, Any]:
    try:
        symbols   = [symbol] if symbol else [p.symbol for p in state.portfolio.get_positions()]
        cancelled = 0
        for sym in symbols:
            await state.client.cancel_all_orders(sym)
            cancelled += 1
        return {"status": "ok", "symbols_processed": cancelled}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/close_all")
async def close_all(state: AppState = Depends(get_state)) -> Dict[str, Any]:
    if not state.portfolio.is_ready:
        raise HTTPException(status_code=503, detail="Not reconciled")
    positions      = state.portfolio.get_positions()
    closed, errors = [], []
    cfg            = get_settings()
    mode           = MarketMode.FUTURES if cfg.futures_enabled else MarketMode.SPOT
    for pos in positions:
        try:
            close_side = OrderSide.SELL if pos.side == "BUY" else OrderSide.BUY
            await state.execution.place_order(
                OrderRequest(
                    symbol=pos.symbol,
                    side=close_side,
                    order_type=OrderType.MARKET,
                    quantity=Decimal(str(pos.quantity)),
                    market_mode=mode,
                    idempotency_key=uuid4(),
                    reduce_only=True,
                )
            )
            state.portfolio.remove_position(pos.symbol)
            closed.append(pos.symbol)
        except Exception as exc:
            errors.append({"symbol": pos.symbol, "error": str(exc)})
    return {"closed": closed, "errors": errors}

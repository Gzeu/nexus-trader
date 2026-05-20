"""
FastAPI routes — toate endpoint-urile REST ale sistemului.
"/api/v1/" prefix aplicat in app.py.

CHANGELOG:
  🔴 /metrics citeste live din get_balance_summary() + get_risk_metrics()
     (nu mai returneaza _cached_equity stale=0.0)
  🔴 /signals fara response_model — returneaza List[dict] cu signal_status atasat
  🟡 peak_equity expus prin state.risk.peak_equity (property public in risk_manager)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.api.state import AppState, get_state
from backend.config import get_settings
from backend.models import Order, Position
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
    Dashboard metrics: equity LIVE din Binance + analytics din trade history.

    FIX 🔴: Fetch-uieste live la fiecare apel prin get_balance_summary().
    Anterior returna _cached_equity stale (setat o singura data la reconciliere).
    Fallback la valoarea cached daca Binance e momentan indisponibil.
    """
    # 1. Equity + balance LIVE
    try:
        balance = await state.portfolio.get_balance_summary()
        total_equity   = balance.total_usdt_value
        available      = balance.available_margin
        unrealized_pnl = balance.unrealized_pnl
    except Exception as exc:
        logger.warning("metrics: balance fetch failed (%s), falling back to cached equity", exc)
        total_equity   = state.portfolio.get_equity()
        available      = 0.0
        unrealized_pnl = 0.0

    # 2. Trade analytics din state local
    rm = state.portfolio.get_risk_metrics()

    # 3. Risk manager live state (peak_equity acum property public)
    peak_eq = state.risk.peak_equity  # 🟡 property public adaugat in risk_manager.py
    drawdown_pct = round(
        (1.0 - total_equity / peak_eq) * 100, 2
    ) if peak_eq > 0 else 0.0

    return {
        "equity":            round(total_equity, 2),
        "available":         round(available, 2),
        "unrealized_pnl":    round(unrealized_pnl, 2),
        "realized_pnl":      round(rm.gross_profit - rm.gross_loss, 2),
        "win_rate":          rm.win_rate,
        "winning_trades":    rm.winning_trades,
        "losing_trades":     rm.losing_trades,
        "total_trades":      rm.total_trades,
        "profit_factor":     rm.profit_factor,
        "sharpe_ratio":      rm.sharpe_ratio,
        "expectancy":        rm.expectancy,
        "risk": {
            "paused":             state.risk.is_paused,
            "consecutive_losses": state.risk.consecutive_losses,
            "daily_pnl":          state.risk.daily_pnl,
            "drawdown_pct":       drawdown_pct,
            "max_drawdown_seen":  state.risk.max_drawdown_seen,
        },
    }


# ─────────────────────────────────────────── account / balance

@router.get("/account", response_model=AccountInfo)
async def get_account(state: AppState = Depends(get_state)) -> AccountInfo:
    """Full account snapshot (spot + futures)."""
    return await state.portfolio.get_account_info()


@router.get("/balance", response_model=BalanceSummary)
async def get_balance(state: AppState = Depends(get_state)) -> BalanceSummary:
    """Aggregated USDT balance summary pentru dashboard."""
    return await state.portfolio.get_balance_summary()


# ─────────────────────────────────────────── positions / orders

@router.get("/positions", response_model=List[Position])
async def get_positions(state: AppState = Depends(get_state)) -> List[Position]:
    return state.portfolio.get_positions()


@router.get("/orders", response_model=List[Order])
async def get_orders(state: AppState = Depends(get_state)) -> List[Order]:
    return state.portfolio.get_open_orders()


# ─────────────────────────────────────────── signals

@router.get("/signals")
async def get_signals(
    limit: int = Query(default=50, ge=1, le=200),
    state: AppState = Depends(get_state),
) -> List[Dict[str, Any]]:
    """
    Ultimele N semnale generate de AutomationEngine.

    FIX 🔴: Eliminat response_model=List[StrategySignal] care facea Pydantic
    sa valideze dict-urile (cu signal_status extra) si returna [] silentios.
    Acum returneaza direct List[dict].
    """
    return state.automation.get_recent_signals(limit=limit)


# ─────────────────────────────────────────── manual order

class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str  # "BUY" | "SELL"
    quantity: float
    order_type: str = "MARKET"
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@router.post("/place_order")
async def place_order(
    req: PlaceOrderRequest,
    state: AppState = Depends(get_state),
) -> Dict[str, Any]:
    if not state.portfolio.is_ready:
        raise HTTPException(status_code=503, detail="System not reconciled — trading blocked")
    if state.risk.is_paused:
        raise HTTPException(status_code=503, detail="Risk manager paused — trading blocked")
    try:
        result = await state.execution.place_order(
            symbol=req.symbol,
            side=req.side,
            quantity=req.quantity,
            order_type=req.order_type,
            price=req.price,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
        )
        return {"success": True, "order": result}
    except Exception as exc:
        logger.error("place_order failed: %s", exc)
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
    logger.info("Trading resumed via API")
    return {"status": "trading_resumed"}


@router.post("/cancel_all")
async def cancel_all(
    symbol: Optional[str] = Query(default=None),
    state: AppState = Depends(get_state),
) -> Dict[str, Any]:
    try:
        symbols = [symbol] if symbol else [p.symbol for p in state.portfolio.get_positions()]
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
    return {"closed": closed, "errors": errors}

"""
routes.py – All HTTP REST endpoints.

Endpoints:
  GET  /health             – liveness + readiness
  GET  /metrics            – risk + portfolio analytics
  GET  /signals            – last 50 trades from journal
  POST /place_order        – manual order placement
  POST /emergency_stop     – pause trading + kill automation
  POST /resume_trading     – resume after pause
  POST /cancel_all         – cancel open orders (optional symbol filter)
  POST /close_all          – market-close all open positions
  GET  /positions          – current open positions
  GET  /account            – account balance info
"""
from __future__ import annotations

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.models import MarketMode, OrderSide

log = structlog.get_logger(__name__)
router = APIRouter()


def get_ctx(request: Request):
    return request.app.state.ctx


# ── Health ──────────────────────────────────────────────────────────────────

@router.get("/health")
async def health(ctx=Depends(get_ctx)):
    return {
        "status": "ok" if (ctx.portfolio and ctx.portfolio.is_ready) else "not_reconciled",
        "dry_run": ctx.settings.dry_run,
        "testnet": ctx.settings.testnet,
        "automation_running": bool(ctx.automation and ctx.automation._running),
        "trading_paused": ctx.risk.paused if ctx.risk else True,
        "pause_reason": ctx.risk.pause_reason if ctx.risk else "not_initialized",
    }


# ── Metrics ──────────────────────────────────────────────────────────────────

@router.get("/metrics")
async def metrics(ctx=Depends(get_ctx)):
    if not ctx.portfolio:
        raise HTTPException(503, "Portfolio not initialized")
    risk_metrics = ctx.risk.get_metrics()
    portfolio_summary = ctx.portfolio.get_summary()
    return {**risk_metrics.model_dump(), **portfolio_summary}


# ── Signals / Journal ─────────────────────────────────────────────────────────

@router.get("/signals")
async def list_signals(ctx=Depends(get_ctx)):
    trades = await ctx.journal.get_trades()
    return {"count": len(trades), "trades": trades[-50:]}


# ── Place Order ───────────────────────────────────────────────────────────────

class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str  # BUY | SELL
    quantity: float
    price: Optional[float] = None  # None → market order
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    market_mode: str = "SPOT"  # SPOT | FUTURES


@router.post("/place_order")
async def place_order(req: PlaceOrderRequest, ctx=Depends(get_ctx)):
    """Place a manual order. Reconciliation must have succeeded."""
    if not ctx.portfolio or not ctx.portfolio.is_ready:
        raise HTTPException(503, "System not reconciled – trading blocked")
    if ctx.risk.paused:
        raise HTTPException(403, f"Trading paused: {ctx.risk.pause_reason}")

    side = OrderSide.BUY if req.side.upper() == "BUY" else OrderSide.SELL
    mode = MarketMode.FUTURES if req.market_mode.upper() == "FUTURES" else MarketMode.SPOT

    try:
        if req.price:
            order = await ctx.execution.place_limit_order(
                req.symbol, side, req.quantity, req.price, market_mode=mode
            )
        else:
            order = await ctx.execution.place_market_order(
                req.symbol, side, req.quantity, market_mode=mode
            )
        log.info("manual_order_placed", symbol=req.symbol, side=req.side, qty=req.quantity)
        return order.model_dump(mode="json")
    except Exception as exc:
        log.error("manual_order_error", error=str(exc))
        raise HTTPException(500, str(exc))


# ── Safety Endpoints ──────────────────────────────────────────────────────────

@router.post("/emergency_stop")
async def emergency_stop(ctx=Depends(get_ctx)):
    """Immediately pause all trading and stop automation scheduler."""
    ctx.risk._pause("Manual emergency stop via API")
    if ctx.automation:
        ctx.automation.stop()
    log.critical("emergency_stop_triggered")
    from backend.journal.telegram_alerts import send_alert
    await send_alert("🚨 EMERGENCY STOP triggered manually via API")
    return {"status": "stopped", "paused": True}


@router.post("/resume_trading")
async def resume_trading(ctx=Depends(get_ctx)):
    """Resume trading after manual pause."""
    ctx.risk.resume()
    if ctx.automation:
        ctx.automation.start()
    log.info("trading_resumed")
    return {"status": "resumed", "paused": False}


@router.post("/cancel_all")
async def cancel_all(symbol: Optional[str] = None, ctx=Depends(get_ctx)):
    """Cancel all open orders, optionally filtered by symbol."""
    try:
        result = await ctx.spot_client.cancel_all_orders(symbol or "")
        return {"cancelled": result}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/close_all")
async def close_all(ctx=Depends(get_ctx)):
    """Market-close every open position."""
    results = []
    for sym, pos in list(ctx.portfolio.positions.items()):
        try:
            await ctx.execution.close_position(pos)
            ctx.portfolio.remove_position(sym)
            results.append({"symbol": sym, "status": "closed"})
            log.info("position_closed", symbol=sym)
        except Exception as exc:
            log.error("close_position_error", symbol=sym, error=str(exc))
            results.append({"symbol": sym, "error": str(exc)})
    return {"results": results}


# ── Read-only state ────────────────────────────────────────────────────────────

@router.get("/positions")
async def get_positions(ctx=Depends(get_ctx)):
    return [p.model_dump(mode="json") for p in ctx.portfolio.positions.values()]


@router.get("/account")
async def get_account(ctx=Depends(get_ctx)):
    return ctx.portfolio.account.model_dump(mode="json")

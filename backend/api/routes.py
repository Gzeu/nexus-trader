"""
routes.py – HTTP REST endpoints.
"""
from __future__ import annotations

from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.models import MarketMode, Order, OrderSide, OrderStatus, StrategySignal

log = structlog.get_logger(__name__)
router = APIRouter()


def get_ctx(request: Request):
    return request.app.state.ctx


@router.get("/health")
async def health(ctx=Depends(get_ctx)):
    return {
        "status": "ok" if ctx.portfolio and ctx.portfolio.is_ready else "not_reconciled",
        "dry_run": ctx.settings.dry_run,
        "testnet": ctx.settings.testnet,
        "automation_running": ctx.automation._running if ctx.automation else False,
    }


@router.get("/metrics")
async def metrics(ctx=Depends(get_ctx)):
    if not ctx.portfolio:
        raise HTTPException(503, "Portfolio not initialized")
    risk_metrics = ctx.risk.get_metrics()
    portfolio_summary = ctx.portfolio.get_summary()
    return {**risk_metrics.model_dump(), **portfolio_summary}


@router.get("/signals")
async def list_signals(ctx=Depends(get_ctx)):
    trades = await ctx.journal.get_trades()
    return {"count": len(trades), "trades": trades[-50:]}


class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    price: Optional[float] = None
    market_mode: str = "SPOT"


@router.post("/place_order")
async def place_order(req: PlaceOrderRequest, ctx=Depends(get_ctx)):
    if not ctx.portfolio or not ctx.portfolio.is_ready:
        raise HTTPException(503, "System not reconciled – trading blocked")
    if ctx.risk.paused:
        raise HTTPException(403, f"Trading paused: {ctx.risk.pause_reason}")

    side = OrderSide.BUY if req.side.upper() == "BUY" else OrderSide.SELL
    mode = MarketMode.FUTURES if req.market_mode.upper() == "FUTURES" else MarketMode.SPOT

    try:
        if req.price:
            order = await ctx.execution.place_limit_order(req.symbol, side, req.quantity, req.price, market_mode=mode)
        else:
            order = await ctx.execution.place_market_order(req.symbol, side, req.quantity, market_mode=mode)
        return order.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/emergency_stop")
async def emergency_stop(ctx=Depends(get_ctx)):
    ctx.risk._pause("Manual emergency stop")
    ctx.automation.stop()
    from backend.journal.telegram_alerts import send_alert
    await send_alert("🚨 EMERGENCY STOP triggered manually")
    return {"status": "stopped"}


@router.post("/resume_trading")
async def resume_trading(ctx=Depends(get_ctx)):
    ctx.risk.resume()
    ctx.automation.start()
    return {"status": "resumed"}


@router.post("/cancel_all")
async def cancel_all(symbol: Optional[str] = None, ctx=Depends(get_ctx)):
    try:
        result = await ctx.spot_client.cancel_all_orders(symbol or "")
        return {"cancelled": result}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/close_all")
async def close_all(ctx=Depends(get_ctx)):
    results = []
    for sym, pos in list(ctx.portfolio.positions.items()):
        try:
            await ctx.execution.close_position(pos)
            ctx.portfolio.remove_position(sym)
            results.append({"symbol": sym, "status": "closed"})
        except Exception as exc:
            results.append({"symbol": sym, "error": str(exc)})
    return {"results": results}


@router.get("/positions")
async def get_positions(ctx=Depends(get_ctx)):
    return [p.model_dump(mode="json") for p in ctx.portfolio.positions.values()]


@router.get("/account")
async def get_account(ctx=Depends(get_ctx)):
    return ctx.portfolio.account.model_dump(mode="json")

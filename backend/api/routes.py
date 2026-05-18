"""
routes.py – All HTTP REST endpoints for Nexus Trader.

Endpoints
---------
GET  /health          – System status (reconciled, dry_run, automation)
GET  /metrics         – Risk + portfolio analytics
GET  /signals         – Last 50 trade records from journal
POST /place_order     – Manual order placement (blocked if paused/not reconciled)
POST /emergency_stop  – Halt automation + pause risk engine
POST /resume_trading  – Resume after pause
POST /cancel_all      – Cancel all open orders (optional symbol filter)
POST /close_all       – Close every open position at market
GET  /positions       – Current open positions
GET  /account         – Account balances + equity
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
        "trading_paused": ctx.risk.paused,
        "pause_reason": ctx.risk.pause_reason,
        "automation_running": ctx.automation._running if ctx.automation else False,
        "open_positions": len(ctx.portfolio.positions) if ctx.portfolio else 0,
    }


# ── Metrics ─────────────────────────────────────────────────────────────────

@router.get("/metrics")
async def metrics(ctx=Depends(get_ctx)):
    if not ctx.portfolio:
        raise HTTPException(503, "Portfolio not initialized")
    risk_metrics = ctx.risk.get_metrics()
    portfolio_summary = ctx.portfolio.get_summary()
    return {**risk_metrics.model_dump(), **portfolio_summary}


# ── Signals / Journal ───────────────────────────────────────────────────────

@router.get("/signals")
async def list_signals(ctx=Depends(get_ctx)):
    trades = await ctx.journal.get_trades()
    return {"count": len(trades), "trades": trades[-50:]}


# ── Order Placement ──────────────────────────────────────────────────────────

class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str                        # "BUY" | "SELL"
    quantity: float
    price: Optional[float] = None    # None → MARKET order
    market_mode: str = "SPOT"        # "SPOT" | "FUTURES"


@router.post("/place_order")
async def place_order(req: PlaceOrderRequest, ctx=Depends(get_ctx)):
    if not ctx.portfolio or not ctx.portfolio.is_ready:
        raise HTTPException(503, "System not reconciled – trading blocked until startup sync completes")
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
        await ctx.journal.log_order(order)
        return order.model_dump(mode="json")
    except Exception as exc:
        log.error("place_order_error", symbol=req.symbol, error=str(exc))
        raise HTTPException(500, str(exc))


# ── Kill Switches ────────────────────────────────────────────────────────────

@router.post("/emergency_stop")
async def emergency_stop(ctx=Depends(get_ctx)):
    ctx.risk._pause("Manual emergency stop via API")
    ctx.automation.stop()
    log.critical("emergency_stop_triggered")
    from backend.journal.telegram_alerts import send_alert
    await send_alert("🚨 EMERGENCY STOP triggered via /emergency_stop endpoint")
    return {"status": "stopped", "message": "Automation halted. Call /resume_trading to restart."}


@router.post("/resume_trading")
async def resume_trading(ctx=Depends(get_ctx)):
    ctx.risk.resume()
    ctx.automation.start()
    log.info("trading_resumed")
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
            log.error("close_all_error", symbol=sym, error=str(exc))
            results.append({"symbol": sym, "error": str(exc)})
    return {"results": results}


# ── Portfolio ────────────────────────────────────────────────────────────────

@router.get("/positions")
async def get_positions(ctx=Depends(get_ctx)):
    if not ctx.portfolio:
        raise HTTPException(503, "Portfolio not initialized")
    return [p.model_dump(mode="json") for p in ctx.portfolio.positions.values()]


@router.get("/account")
async def get_account(ctx=Depends(get_ctx)):
    if not ctx.portfolio:
        raise HTTPException(503, "Portfolio not initialized")
    return ctx.portfolio.account.model_dump(mode="json")

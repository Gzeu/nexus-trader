"""
routes.py – All HTTP REST endpoints for Nexus Trader v3.

Changelog v3.1:
- /balance endpoint added (BalanceSummary: Spot + Futures + unrealized PnL)
- All imports from backend.models (models_extra removed)
"""
from __future__ import annotations

import time
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.models import (
    AccountInfo,
    AssetBalance,
    BalanceSummary,
    FuturesAsset,
    HealthResponse,
    MarketMode,
    OrderRequest,
    OrderSide,
    OrderType,
    PlaceOrderBody,
    PositionState,
    RiskVeto,
    WSEventType,
)

log = structlog.get_logger(__name__)
router = APIRouter()


def get_ctx(request: Request):
    return request.app.state.ctx


def require_ready(ctx) -> None:
    """Raise 503 if system is not reconciled."""
    if not ctx.portfolio or not ctx.portfolio.is_ready:
        raise HTTPException(
            503,
            detail="System not reconciled. Call POST /api/v1/reconcile or wait for startup.",
        )


# ── Health ───────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health(request: Request, ctx=Depends(get_ctx)):
    reconciled = bool(ctx.portfolio and ctx.portfolio.is_ready)

    binance_ok = True
    try:
        import asyncio
        await asyncio.wait_for(ctx.spot_client.ping(), timeout=2.0)
    except Exception:
        binance_ok = False

    start_time = getattr(request.app.state, "start_time", time.monotonic())
    uptime = time.monotonic() - start_time

    return HealthResponse(
        status="ok" if reconciled else "degraded",
        reconciled=reconciled,
        dry_run=ctx.settings.dry_run,
        testnet=ctx.settings.testnet,
        open_positions=len(ctx.portfolio.positions) if ctx.portfolio else 0,
        equity=ctx.portfolio.account.total_equity if (ctx.portfolio and ctx.portfolio.account) else 0.0,
        paused=ctx.risk.paused,
        binance_reachable=binance_ok,
        last_reconcile=ctx.portfolio._last_reconcile if ctx.portfolio else None,
        uptime_seconds=uptime,
        version="3.1.0",
    )


# ── Metrics ───────────────────────────────────────────────────────────────────

@router.get("/analytics")
async def analytics(ctx=Depends(get_ctx)):
    """Risk metrics + portfolio analytics merged into one response."""
    if not ctx.portfolio:
        raise HTTPException(503, "Portfolio not initialized")
    risk_metrics = ctx.risk.get_metrics().model_dump()
    portfolio_summary = ctx.portfolio.get_analytics()
    return {**risk_metrics, **portfolio_summary}


# ── Balance ──────────────────────────────────────────────────────────────────

@router.get("/balance", response_model=BalanceSummary)
async def get_balance(ctx=Depends(get_ctx)):
    """
    Aggregated USDT balance summary: Spot + Futures + unrealized PnL.
    Returns immediately from cache if portfolio not yet reconciled.
    Never raises 500 — falls back to cached equity on Binance errors.
    """
    if not ctx.portfolio:
        raise HTTPException(503, "Portfolio not initialized")
    return (await ctx.portfolio.get_balance_summary()).model_dump(mode="json")


@router.get("/account", response_model=AccountInfo)
async def get_account_full(ctx=Depends(get_ctx)):
    """
    Full account snapshot: all spot balances + all futures assets.
    Slower than /balance — makes two live Binance calls.
    """
    if not ctx.portfolio:
        raise HTTPException(503, "Portfolio not initialized")
    return (await ctx.portfolio.get_account_info()).model_dump(mode="json")


# ── Signals / Journal ────────────────────────────────────────────────────────────

@router.get("/signals")
async def list_signals(
    limit: int = Query(default=50, ge=1, le=500),
    ctx=Depends(get_ctx),
):
    trades = await ctx.journal.get_trades(limit=limit)
    return {"count": len(trades), "trades": trades}


# ── Order placement ──────────────────────────────────────────────────────────────

@router.post("/place_order")
async def place_order(body: PlaceOrderBody, ctx=Depends(get_ctx)):
    require_ready(ctx)
    if ctx.risk.paused:
        raise HTTPException(403, f"Trading paused: {ctx.risk.pause_reason}")
    if body.symbol.upper() in ctx.settings.symbol_blacklist:
        raise HTTPException(400, f"{body.symbol} is blacklisted")

    mode = (
        MarketMode.FUTURES
        if str(body.market_mode).upper() == "FUTURES"
        else MarketMode.SPOT
    )
    side = OrderSide(body.side.upper()) if isinstance(body.side, str) else body.side
    order_type = (
        OrderType.LIMIT if body.price is not None else OrderType.MARKET
    )

    from decimal import Decimal
    if body.quantity:
        qty = Decimal(str(body.quantity))
    else:
        if not body.stop_loss:
            raise HTTPException(400, "quantity or stop_loss required for auto-sizing")
        from backend.core.trade_logic import calc_position_size
        qty = calc_position_size(
            equity=ctx.risk.equity,
            entry_price=body.price or 0,
            stop_loss=body.stop_loss,
        )

    try:
        request = OrderRequest(
            symbol=body.symbol.upper(),
            side=side,
            order_type=order_type,
            quantity=qty,
            price=Decimal(str(body.price)) if body.price else None,
            stop_price=Decimal(str(body.stop_loss)) if body.stop_loss else None,
            take_profit_price=Decimal(str(body.take_profit)) if body.take_profit else None,
            market_mode=mode,
        )
        order = await ctx.execution.place_order(request)
        await ctx.journal.log_order(order)

        if ctx.ws_broadcast:
            await ctx.ws_broadcast(
                WSEventType.ORDER_PLACED,
                {"symbol": order.symbol, "side": str(order.side), "qty": str(order.quantity)},
            )

        return order.model_dump(mode="json")
    except Exception as exc:
        log.exception("place_order_error", symbol=body.symbol)
        raise HTTPException(500, str(exc))


# ── Kill switches ───────────────────────────────────────────────────────────────────

@router.post("/emergency_stop")
async def emergency_stop(ctx=Depends(get_ctx)):
    ctx.risk._pause("Manual emergency stop via API", pause_type="manual")
    if ctx.automation and ctx.automation.running:
        ctx.automation.stop()
    log.critical("emergency_stop_triggered")

    if ctx.ws_broadcast:
        await ctx.ws_broadcast(WSEventType.EMERGENCY_STOP, {"source": "api"})

    if ctx.settings.is_telegram_configured():
        await ctx.telegram.send_alert(
            "🚨 EMERGENCY STOP triggered via /emergency_stop endpoint"
        )

    return {
        "status": "stopped",
        "message": "Automation halted and risk paused. Call /resume_trading to restart.",
    }


@router.post("/resume_trading")
async def resume_trading(ctx=Depends(get_ctx)):
    ctx.risk.resume()
    if ctx.automation and not ctx.automation.running:
        ctx.automation.start()
    log.info("trading_resumed")
    return {"status": "resumed"}


@router.post("/reconcile")
async def manual_reconcile(ctx=Depends(get_ctx)):
    """Manually trigger full portfolio reconciliation."""
    if not ctx.portfolio:
        raise HTTPException(503, "Portfolio not initialized")
    try:
        result = await ctx.portfolio.reconcile()
        return result.model_dump(mode="json")
    except Exception as exc:
        log.exception("manual_reconcile_error")
        raise HTTPException(500, str(exc))


@router.post("/cancel_all")
async def cancel_all(
    symbol: Optional[str] = Query(default=None, description="Cancel for specific symbol only"),
    ctx=Depends(get_ctx),
):
    if not ctx.execution:
        raise HTTPException(503, "Execution engine not initialized")
    symbols = [symbol] if symbol else ctx.settings.symbol_whitelist
    results = {}
    for sym in symbols:
        mode = (
            MarketMode.FUTURES
            if ctx.settings.futures_enabled
            else MarketMode.SPOT
        )
        count = await ctx.execution.cancel_all_orders(sym, mode)
        results[sym] = count
    return {"cancelled": results}


@router.post("/close_all")
async def close_all(ctx=Depends(get_ctx)):
    require_ready(ctx)
    results = []
    for sym, pos in list(ctx.portfolio.positions.items()):
        try:
            from decimal import Decimal
            close_side = (
                OrderSide.SELL
                if str(pos.side) in ("LONG", "BUY")
                else OrderSide.BUY
            )
            close_req = OrderRequest(
                symbol=sym,
                side=close_side,
                order_type=OrderType.MARKET,
                quantity=pos.remaining_quantity or pos.quantity,
                market_mode=pos.market_mode,
                reduce_only=ctx.settings.futures_enabled,
            )
            order = await ctx.execution.place_order(close_req)
            ctx.portfolio.remove_position(sym)
            ctx.risk.position_closed(sym)
            results.append({"symbol": sym, "status": "closed", "order_id": order.exchange_order_id})
        except Exception as exc:
            log.exception("close_all_error", symbol=sym)
            results.append({"symbol": sym, "error": str(exc)})
    return {"results": results}


# ── Positions ───────────────────────────────────────────────────────────────────

@router.get("/positions")
async def get_positions(ctx=Depends(get_ctx)):
    if not ctx.portfolio:
        raise HTTPException(503, "Portfolio not initialized")
    return [
        PositionState.from_position(p).model_dump()
        for p in ctx.portfolio.positions.values()
    ]


# ── Pine Script webhook ───────────────────────────────────────────────────────────

from pydantic import BaseModel as _BaseModel


class PineScriptAlert(_BaseModel):
    """Expected JSON payload from TradingView Pine Script alert webhook."""
    symbol: str
    action: str       # "BUY" | "SELL" | "CLOSE"
    price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    timeframe: Optional[str] = None
    comment: Optional[str] = None
    secret: Optional[str] = None


@router.post("/webhook/pine")
async def pine_webhook(alert: PineScriptAlert, ctx=Depends(get_ctx)):
    """
    Receive Pine Script alerts from TradingView and convert to orders.

    TradingView alert message template:
      {"symbol":"{{ticker}}","action":"BUY","price":{{close}},
       "stop_loss":{{strategy.order.price}},"comment":"{{strategy.order.comment}}"}
    """
    if ctx.settings.api_secret_key and ctx.settings.environment == "production":
        if alert.secret != ctx.settings.api_secret_key:
            raise HTTPException(401, "Invalid webhook secret")

    require_ready(ctx)
    if ctx.risk.paused:
        raise HTTPException(403, f"Trading paused: {ctx.risk.pause_reason}")

    log.info("pine_webhook_received", symbol=alert.symbol, action=alert.action, price=alert.price)

    if alert.action.upper() == "CLOSE":
        pos = ctx.portfolio.get_position(alert.symbol.upper())
        if not pos:
            return {"status": "no_position", "symbol": alert.symbol}
        close_side = (
            OrderSide.SELL if str(pos.side) in ("LONG", "BUY") else OrderSide.BUY
        )
        req = OrderRequest(
            symbol=alert.symbol.upper(),
            side=close_side,
            order_type=OrderType.MARKET,
            quantity=pos.remaining_quantity or pos.quantity,
            market_mode=MarketMode.FUTURES if ctx.settings.futures_enabled else MarketMode.SPOT,
            reduce_only=ctx.settings.futures_enabled,
        )
        order = await ctx.execution.place_order(req)
        ctx.portfolio.remove_position(alert.symbol.upper())
        ctx.risk.position_closed(alert.symbol.upper())
        return {"status": "closed", "order": order.model_dump(mode="json")}

    body = PlaceOrderBody(
        symbol=alert.symbol.upper(),
        side=alert.action.upper(),
        price=alert.price,
        stop_loss=alert.stop_loss,
        take_profit=alert.take_profit,
        market_mode="FUTURES" if ctx.settings.futures_enabled else "SPOT",
    )
    return await place_order(body, ctx)

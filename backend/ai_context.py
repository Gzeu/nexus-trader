"""
ai_context.py — Construiește system prompt-ul AI Copilot cu date live.

Injectează în prompt:
  - Equity, available margin, unrealized PnL
  - Risk state (paused, drawdown, daily PnL, consecutive losses)
  - Pozițiile deschise curente (symbol, side, size, entry, unrealized PnL)
  - Ultimele 5 semnale generate de AutomationEngine
  - Configurație sistem (dry_run, testnet, market_mode, automation running)

Folosit exclusiv de ai_routes.py → POST /api/v1/ai/chat.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.api.state import AppState

logger = logging.getLogger(__name__)


async def build_system_prompt(state: AppState) -> str:
    """
    Construiește un system prompt detaliat cu starea live a sistemului.
    Toate erorile de fetch sunt prinse — prompt-ul se construiește parțial
    dacă unele date nu sunt disponibile momentan.
    """
    lines: list[str] = [
        "Ești NexusTrader AI Copilot, un asistent expert în trading automatizat pe Binance (Spot + Futures).",
        "Răspunzi în română sau engleză în funcție de limbajul user-ului.",
        "Ești concis, direct și bazat pe date. Nu inventa cifre.",
        "",
        f"=== STAREA SISTEMULUI (actualizat: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}) ===",
    ]

    # ── Config de bază ────────────────────────────────────────────────────────
    try:
        from backend.config import get_settings
        cfg = get_settings()
        lines += [
            f"Mod: {'DRY RUN (simulare, fără ordine reale)' if cfg.dry_run else 'LIVE TRADING'}",
            f"Testnet: {'DA' if cfg.testnet else 'NU'}",
            f"Market mode: {cfg.market_mode.upper()}",
            f"Automation: {'RUNNING' if state.automation.running else 'STOPPED'}",
            f"Simboluri monitorizate: {cfg.symbols}",
        ]
    except Exception as exc:
        logger.warning("ai_context: config fetch failed: %s", exc)
        lines.append("Config: indisponibil momentan")

    # ── Metrics / Equity ──────────────────────────────────────────────────────
    lines.append("")
    lines.append("--- Financiar ---")
    try:
        balance = await state.portfolio.get_balance_summary()
        lines += [
            f"Equity total: ${balance.total_usdt_value:.2f} USDT",
            f"Margin disponibil: ${balance.available_margin:.2f} USDT",
            f"Unrealized PnL: ${balance.unrealized_pnl:.2f} USDT",
        ]
    except Exception as exc:
        logger.warning("ai_context: balance fetch failed: %s", exc)
        # Fallback la equity cached
        equity = state.portfolio.get_equity()
        lines.append(f"Equity (cached): ${equity:.2f} USDT (date live indisponibile)")

    # ── Risk state ────────────────────────────────────────────────────────────
    lines.append("")
    lines.append("--- Risk Manager ---")
    try:
        rm = state.risk
        peak = rm.peak_equity
        equity_now = state.portfolio.get_equity()
        drawdown = round((1.0 - equity_now / peak) * 100, 2) if peak > 0 else 0.0
        lines += [
            f"Status: {'⛔ PAUZAT' if rm.is_paused else '✅ ACTIV'}",
            f"Daily PnL: ${rm.daily_pnl:.2f} USDT",
            f"Drawdown curent: {drawdown}%",
            f"Max drawdown văzut: {rm.max_drawdown_seen:.2f}%",
            f"Pierderi consecutive: {rm.consecutive_losses}",
        ]
    except Exception as exc:
        logger.warning("ai_context: risk state failed: %s", exc)
        lines.append("Risk state: indisponibil")

    # ── Poziții deschise ──────────────────────────────────────────────────────
    lines.append("")
    lines.append("--- Poziții deschise ---")
    try:
        positions = state.portfolio.get_positions()
        if not positions:
            lines.append("Nicio poziție deschisă.")
        else:
            for pos in positions:
                upnl = pos.unrealized_pnl if pos.unrealized_pnl is not None else 0.0
                lines.append(
                    f"  {pos.symbol} {pos.side} | qty={pos.quantity} "
                    f"| entry=${pos.entry_price:.4f} "
                    f"| uPnL=${upnl:.2f}"
                )
    except Exception as exc:
        logger.warning("ai_context: positions failed: %s", exc)
        lines.append("Poziții: indisponibile")

    # ── Ultimele semnale ──────────────────────────────────────────────────────
    lines.append("")
    lines.append("--- Ultimele 5 semnale ---")
    try:
        signals = state.automation.get_recent_signals(limit=5)
        if not signals:
            lines.append("Niciun semnal recent.")
        else:
            for sig in signals:
                symbol = sig.get("symbol", "?")
                action = sig.get("action", sig.get("signal_type", "?"))
                confidence = sig.get("confidence", sig.get("strength", ""))
                ts = sig.get("timestamp", sig.get("created_at", ""))
                conf_str = f" | confidence={confidence}" if confidence else ""
                ts_str = f" | {ts}" if ts else ""
                lines.append(f"  {symbol} → {action}{conf_str}{ts_str}")
    except Exception as exc:
        logger.warning("ai_context: signals failed: %s", exc)
        lines.append("Semnale: indisponibile")

    # ── Trade analytics ───────────────────────────────────────────────────────
    lines.append("")
    lines.append("--- Analytics trades ---")
    try:
        rm_stats = state.portfolio.get_risk_metrics()
        lines += [
            f"Total trades: {rm_stats.total_trades}",
            f"Win rate: {rm_stats.win_rate:.1f}%",
            f"Profit factor: {rm_stats.profit_factor:.2f}",
            f"Sharpe ratio: {rm_stats.sharpe_ratio:.2f}",
            f"Expectancy: ${rm_stats.expectancy:.2f}",
        ]
    except Exception as exc:
        logger.warning("ai_context: analytics failed: %s", exc)
        lines.append("Analytics: indisponibile")

    lines += [
        "",
        "=== INSTRUCȚIUNI ===",
        "- Bazează-te EXCLUSIV pe datele de mai sus când răspunzi despre starea sistemului.",
        "- Dacă datele lipsesc, spune că sunt temporar indisponibile.",
        "- Nu executa niciodată ordine reale — ești în modul read-only/analiză.",
        "- La întrebări despre setup/configurație, explică clar pașii.",
    ]

    return "\n".join(lines)

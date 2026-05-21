"""
ai_context.py — Construieste system prompt-ul si contextul live pentru AI Copilot.

Injecteaza date reale din AppState: metrics, positions, signals, risk state.
Astfel LLM-ul are context complet despre starea contului cand raspunde.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from backend.api.state import AppState

logger = logging.getLogger(__name__)


ASSTANT_SYSTEM_PROMPT = """
Esti NexusAI, asistentul inteligent al platformei NexusTrader — un sistem automat
de trading pe Binance Spot si Futures.

ROLUL TAU:
- Analizezi datele live ale contului (equity, pozitii, semnale, risc)
- Raspunzi la intrebari despre starea trading-ului
- Poti propune actiuni concrete: place_order, emergency_stop, resume_trading,
  cancel_all, close_all, close_position, patch_settings
- NU executi niciodata actiuni autonom — propui, iar traderul confirma

CUM PROPUI ACTIUNI:
Cand vrei sa propui o actiune, include in raspuns un bloc JSON special:

<action>
{{
  "type": "place_order" | "emergency_stop" | "resume_trading" | "cancel_all" | "close_all" | "close_position" | "patch_settings",
  "label": "Text scurt afisat pe butonul de confirmare",
  "description": "Explicatie de ce recomanzi aceasta actiune",
  "params": {{ ... parametri specifici actiunii ... }}
}}
</action>

Pentru place_order, params trebuie sa contina:
  symbol, side ("BUY"|"SELL"), quantity, order_type (default "MARKET"),
  price (optional), stop_loss (optional), take_profit (optional)

Pentru patch_settings, params trebuie sa contina:
  data: {{ key: value, ... }} — ex: {{ "risk_per_trade": 0.005 }}

Pentru close_position, params trebuie sa contina:
  symbol (string)

REGULI:
- Fii concis si direct. Datele de trading sunt exacte, nu aproxima.
- Daca nu ai date suficiente, cere clarificari.
- Nu inventa valori — foloseste doar datele din contextul de mai jos.
- Moneda de baza este USDT daca nu se specifica altfel.
- Raspunde intotdeauna in limba in care ti se vorbeste (romana sau engleza).
"""


async def build_context(state: AppState) -> str:
    """Construieste un bloc de context JSON cu datele live din AppState."""
    ctx: Dict[str, Any] = {}

    # 1. Metrics / equity
    try:
        balance = await state.portfolio.get_balance_summary()
        rm = state.portfolio.get_risk_metrics()
        peak_eq = state.risk.peak_equity
        total_eq = balance.total_usdt_value
        drawdown_pct = round((1.0 - total_eq / peak_eq) * 100, 2) if peak_eq > 0 else 0.0
        ctx["account"] = {
            "equity": round(total_eq, 2),
            "available": round(balance.available_margin, 2),
            "unrealized_pnl": round(balance.unrealized_pnl, 2),
            "realized_pnl": round(rm.gross_profit - rm.gross_loss, 2),
            "win_rate": rm.win_rate,
            "total_trades": rm.total_trades,
            "profit_factor": rm.profit_factor,
            "drawdown_pct": drawdown_pct,
        }
    except Exception as exc:
        logger.warning("ai_context: balance fetch failed: %s", exc)
        ctx["account"] = {"error": "balance unavailable"}

    # 2. Risk state
    ctx["risk"] = {
        "is_paused": state.risk.is_paused,
        "pause_reason": getattr(state.risk, "pause_reason", None),
        "consecutive_losses": state.risk.consecutive_losses,
        "daily_pnl": state.risk.daily_pnl,
        "max_drawdown_seen": state.risk.max_drawdown_seen,
    }

    # 3. Pozitii deschise
    try:
        positions = state.portfolio.get_positions()
        ctx["open_positions"] = [
            {
                "symbol": p.symbol,
                "side": p.side,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
                "unrealized_pnl": p.unrealized_pnl,
                "stop_loss": p.stop_loss,
                "take_profit_1": p.take_profit_1,
            }
            for p in positions
        ]
    except Exception as exc:
        logger.warning("ai_context: positions fetch failed: %s", exc)
        ctx["open_positions"] = []

    # 4. Ultimele 5 semnale
    try:
        signals = state.automation.get_recent_signals(limit=5)
        ctx["recent_signals"] = signals
    except Exception as exc:
        logger.warning("ai_context: signals fetch failed: %s", exc)
        ctx["recent_signals"] = []

    # 5. System config relevant
    from backend.config import get_settings
    cfg = get_settings()
    ctx["config"] = {
        "market_mode": cfg.market_mode,
        "dry_run": cfg.dry_run,
        "testnet": cfg.testnet,
        "symbols": cfg.symbols_list,
        "max_positions": cfg.max_positions,
        "risk_per_trade": cfg.risk_per_trade,
        "max_daily_loss": cfg.max_daily_loss,
        "max_drawdown": cfg.max_drawdown,
        "automation_running": state.automation.running,
    }

    return json.dumps(ctx, indent=2, default=str)

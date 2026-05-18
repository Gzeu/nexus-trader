"""
settings_routes.py – GET/PATCH /settings endpoint.
Reads current config and allows runtime overrides stored in a local JSON file.
Credentials (API keys) are NEVER returned or accepted via this endpoint.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import Settings, get_settings

OVERRIDES_FILE = Path("./overrides.json")
SENSITIVE_KEYS = {
    "binance_api_key", "binance_api_secret",
    "binance_futures_api_key", "binance_futures_api_secret",
    "api_secret_key", "telegram_bot_token",
}

router = APIRouter(prefix="/api/v1", tags=["settings"])


def _load_overrides() -> Dict[str, Any]:
    if OVERRIDES_FILE.exists():
        try:
            return json.loads(OVERRIDES_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_overrides(data: Dict[str, Any]) -> None:
    OVERRIDES_FILE.write_text(json.dumps(data, indent=2))


def _settings_dict(s: Settings) -> Dict[str, Any]:
    d = s.model_dump()
    for k in SENSITIVE_KEYS:
        if k in d and d[k]:
            d[k] = "••••••••"
    return d


class SettingsPatch(BaseModel):
    data: Dict[str, Any]


@router.get("/settings")
async def get_settings_endpoint():
    s = get_settings()
    return {
        "settings": _settings_dict(s),
        "overrides": _load_overrides(),
        "sensitive_keys": list(SENSITIVE_KEYS),
    }


@router.patch("/settings")
async def patch_settings(body: SettingsPatch):
    blocked = [k for k in body.data if k in SENSITIVE_KEYS]
    if blocked:
        raise HTTPException(400, f"Cannot update sensitive keys via API: {blocked}")

    overrides = _load_overrides()
    overrides.update(body.data)
    _save_overrides(overrides)

    return {"ok": True, "message": "Overrides saved. Restart backend to apply.", "overrides": overrides}


@router.delete("/settings/overrides")
async def reset_overrides():
    if OVERRIDES_FILE.exists():
        OVERRIDES_FILE.unlink()
    return {"ok": True, "message": "All overrides cleared."}

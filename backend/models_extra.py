"""
DEPRECATED — kept only for backward compatibility.
All models have been merged into backend/models.py.

Do NOT import from here. Use:
    from backend.models import AccountInfo, AssetBalance, BalanceSummary, FuturesAsset
"""
from backend.models import AccountInfo, AssetBalance, BalanceSummary, FuturesAsset  # noqa: F401

__all__ = ["AccountInfo", "AssetBalance", "BalanceSummary", "FuturesAsset"]

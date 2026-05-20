"""
Backward-compatibility shim.
Toate clasele au fost mutate in backend/models.py.
Acest fisier re-exporta tot ce era definit anterior aici,
astfel incat niciun import existent nu se rupe.
"""
from backend.models import (  # noqa: F401
    AssetBalance,
    FuturesAsset,
    AccountInfo,
    BalanceSummary,
)

__all__ = ["AssetBalance", "FuturesAsset", "AccountInfo", "BalanceSummary"]

"""
pytest configuration and shared fixtures.
"""
from __future__ import annotations

import os

import pytest

# Force dry-run and testnet for all tests
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("TESTNET", "true")
os.environ.setdefault("BINANCE_API_KEY", "test_key")
os.environ.setdefault("BINANCE_API_SECRET", "test_secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_journal.db")


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default asyncio event loop policy."""
    import asyncio
    return asyncio.DefaultEventLoopPolicy()

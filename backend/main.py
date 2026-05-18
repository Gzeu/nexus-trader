"""
main.py – Uvicorn entry point.

Run:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""
from backend.api.app import create_app

app = create_app()

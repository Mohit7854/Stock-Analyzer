"""FastAPI entrypoint shim for deployment platforms that auto-detect main.py."""

from api_service import app

__all__ = ["app"]

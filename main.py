"""Compatibility shim for Railway/Railpack auto-detection.

Railpack detects ASGI projects and tries `uvicorn main:app`. To avoid a
crash-loop on first deploy when railway.json's startCommand isn't yet
read, we re-export the FastAPI app as `main:app`.
"""

from server import app  # noqa: F401

__all__ = ["app"]

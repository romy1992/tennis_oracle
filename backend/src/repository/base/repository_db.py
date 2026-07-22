"""Legacy DB entrypoint for the repository layer.

Canonical engine / session factory live in ``app.db.session``. This module
re-exports the same objects so import scripts and ``CrudRepository`` share one
connection pool with the FastAPI app (no second ``create_engine``).
"""

from backend.src.app.db.session import SessionLocal, engine

__all__ = ["SessionLocal", "engine"]

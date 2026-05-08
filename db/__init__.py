"""Database package for the orchestration system.

Keep engine/session creation lazy so importing model classes does not require
the database driver to be installed or configured.
"""

from typing import Any

from db.models import Base

__all__ = ["engine", "get_async_session", "Base"]


def __getattr__(name: str) -> Any:
    if name in {"engine", "get_async_session"}:
        from db import db

        return getattr(db, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

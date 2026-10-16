"""Runtime configuration read from the environment."""

import os

DEFAULT_DATABASE_URL = "sqlite:///ideology.db"


def database_url() -> str:
    """Return ``DATABASE_URL`` if set, else a SQLite file in the current directory."""
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL

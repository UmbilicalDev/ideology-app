"""Runtime configuration read from the environment."""

import os
from pathlib import Path

DEFAULT_DATABASE_URL = "sqlite:///ideology.db"
DEFAULT_SOURCE_FILES_DIR = "source_files"


def database_url() -> str:
    """Return ``DATABASE_URL`` if set, else a SQLite file in the current directory."""
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def source_files_dir() -> Path:
    """Return ``SOURCE_FILES_DIR`` if set, else ``source_files`` in the current directory."""
    return Path(os.environ.get("SOURCE_FILES_DIR") or DEFAULT_SOURCE_FILES_DIR)

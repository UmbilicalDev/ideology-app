"""Helpers for the dev-dataset tests: directory snapshots and file hashes."""

import hashlib
import os
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(root: Path) -> dict[str, str]:
    """Every entry under ``root``: a link's target, a directory, or a file's SHA-256."""
    entries: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in sorted(dirnames + filenames):
            path = Path(dirpath) / name
            key = str(path.relative_to(root))
            if path.is_symlink():
                entries[key] = f"link:{os.readlink(path)}"
            elif path.is_dir():
                entries[key] = "dir"
            else:
                entries[key] = sha256(path)
    return entries


def bundle_files(directory: Path) -> dict[str, bytes]:
    """Every file of a bundle directory, by relative path, with its bytes."""
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(Path(directory).rglob("*"))
        if path.is_file()
    }

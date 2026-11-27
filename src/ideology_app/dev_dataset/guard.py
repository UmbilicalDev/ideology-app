"""Where the dev dataset may be written, and the refusals (dev-dataset, D4).

``check_target(url)`` returns the ``Target`` paths or raises ``GuardError``
naming the rule, before anything is written. It only parses the URL, calls
``stat`` / ``samefile``, lists the bundle directory and opens an existing
database read-only (``shared_db.read_only_url``); it never creates a file.

Rules, in order: (a) only a SQLite file URL; (b) never the shared database
(``config.SHARED_DATABASE_PATH``), also through a symbolic or hard link;
(c) never a file named ``ideology.db``; (d) an existing file must be a
dev-seed database (exactly one Election, the dev one); (e) the bundle
directory ``<stem>-bundle`` may hold only the dev slug's bundle.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from ideology_app import config, shared_db
from ideology_app.db import make_engine
from ideology_app.dev_dataset import content

DEFAULT_URL = "sqlite:///data/dev/dev.db"
FORBIDDEN_NAME = "ideology.db"
UNSET_HINT = (
    "unset DATABASE_URL or point it at the dev file (sqlite:///data/dev/dev.db)"
)


class GuardError(Exception):
    """The seed refuses this target; the message names the rule."""


@dataclass(frozen=True)
class Target:
    """Where the seed writes: the database, its bundle root and its temporary directory."""

    url: str
    database: Path
    bundle_root: Path
    temporary: Path

    @property
    def bundle(self) -> Path:
        return self.bundle_root / content.SLUG


def target_for(database: Path) -> Target:
    stem = database.stem
    directory = database.parent
    return Target(
        url=f"sqlite:///{database}",
        database=database,
        bundle_root=directory / f"{stem}-bundle",
        temporary=directory / f".{stem}-seed-tmp",
    )


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _is_dev_database(path: Path) -> bool:
    engine = make_engine(shared_db.read_only_url(path))
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT country, type, date, name FROM elections")
            ).all()
    except Exception:  # not SQLite, no schema, unreadable: not a dev-seed database
        return False
    finally:
        engine.dispose()
    if len(rows) != 1:
        return False
    country, type_, date, name = rows[0]
    return (
        country == content.COUNTRY
        and str(type_) == content.ELECTION_TYPE
        and str(date) == content.ELECTION_DATE.isoformat()
        and name == content.ELECTION_NAME
    )


def check_target(url: str | None) -> Target:
    """The target of ``url`` (``None``: ``DEFAULT_URL``), or ``GuardError``."""
    raw = url or DEFAULT_URL
    path = shared_db.sqlite_path(raw)
    if path is None:
        raise GuardError(
            "the dev dataset is built only in a SQLite file (rule a: not a SQLite file URL); "
            + UNSET_HINT
        )
    path = Path(os.path.abspath(path))
    shared = config.SHARED_DATABASE_PATH
    if path.resolve() == shared.resolve() or _same_file(path, shared):
        raise GuardError(
            f"refusing the shared database {shared} (rule b: also through a link); "
            + UNSET_HINT
        )
    if path.name == FORBIDDEN_NAME or path.resolve().name == FORBIDDEN_NAME:
        raise GuardError(
            f"refusing a file named {FORBIDDEN_NAME} (rule c: shared or production database); "
            + UNSET_HINT
        )
    if path.exists() or path.is_symlink():
        if not path.is_file() or not _is_dev_database(path):
            raise GuardError(
                f"{path} exists and is not a dev-seed database (rule d); delete it or choose "
                "another file"
            )
    target = target_for(path)
    root = target.bundle_root
    if root.exists() or root.is_symlink():
        if root.is_symlink() or not root.is_dir():
            raise GuardError(f"{root} is not a directory (rule e: foreign bundle directory)")
        foreign = sorted(p.name for p in root.iterdir() if p.name != content.SLUG)
        if foreign:
            raise GuardError(
                f"{root} holds {foreign[0]!r}, not only the dev bundle {content.SLUG} "
                "(rule e: foreign bundle directory)"
            )
        own = root / content.SLUG
        if own.exists() and (own.is_symlink() or not own.is_dir()):
            raise GuardError(f"{own} is not a directory (rule e: foreign bundle directory)")
    tmp = target.temporary
    if tmp.is_symlink() or (tmp.exists() and not tmp.is_dir()):
        raise GuardError(f"{tmp} exists and is not a directory; remove it")
    return target


__all__ = ["DEFAULT_URL", "GuardError", "Target", "check_target", "target_for"]

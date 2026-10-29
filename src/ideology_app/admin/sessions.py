"""Server-side Operator sessions, in memory and per process (feedback-admin, Decision 5).

The cookie carries ``secrets.token_urlsafe(32)``; the store keeps only the
token's SHA-256, the username, a CSRF token and two times. A session expires
``idle_seconds`` after its last authenticated request or ``absolute_seconds``
after sign-in, whichever comes first. A restart signs everyone out.
"""

import hashlib
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class AdminSession:
    token_hash: bytes
    username: str
    csrf_token: str
    created: float
    last_seen: float


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


class AdminSessionStore:
    def __init__(
        self,
        idle_seconds: float = 1800,
        absolute_seconds: float = 28800,
        max_sessions: int = 64,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.idle_seconds = idle_seconds
        self.absolute_seconds = absolute_seconds
        self.max_sessions = max_sessions
        self._clock = clock
        self._sessions: dict[bytes, AdminSession] = {}
        self._lock = threading.Lock()

    def _expired(self, session: AdminSession, now: float) -> bool:
        return (
            now - session.last_seen > self.idle_seconds
            or now - session.created > self.absolute_seconds
        )

    def __len__(self) -> int:
        return len(self._sessions)

    def create(self, username: str, replacing: str | None = None) -> tuple[str, AdminSession]:
        """A new token and its session; the session ``replacing`` carried is removed first."""
        with self._lock:
            now = self._clock()
            if replacing:
                self._sessions.pop(_hash(replacing), None)
            if len(self._sessions) >= self.max_sessions:
                for key in [k for k, s in self._sessions.items() if self._expired(s, now)]:
                    del self._sessions[key]
            while len(self._sessions) >= self.max_sessions:
                oldest = min(self._sessions.values(), key=lambda s: s.created)
                del self._sessions[oldest.token_hash]
            token = secrets.token_urlsafe(32)
            session = AdminSession(
                token_hash=_hash(token),
                username=username,
                csrf_token=secrets.token_urlsafe(32),
                created=now,
                last_seen=now,
            )
            self._sessions[session.token_hash] = session
            return token, session

    def get(self, token: str | None) -> AdminSession | None:
        """The live session for ``token`` (its idle time refreshed), else ``None``."""
        if not token:
            return None
        with self._lock:
            now = self._clock()
            key = _hash(token)
            session = self._sessions.get(key)
            if session is None:
                return None
            if self._expired(session, now):
                del self._sessions[key]
                return None
            session.last_seen = now
            return session

    def remove(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(_hash(token), None)


__all__ = ["AdminSession", "AdminSessionStore"]

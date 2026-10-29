"""Per-process abuse guard for ``POST /api/v1/feedback`` (feedback-api, Decision 8).

Reused, as a second instance with its own limits, for Operator sign-in at
``POST /admin/api/v1/session`` (feedback-admin, Decision 8).

Sliding windows: at most ``per_client`` accepted requests per client and
``global_limit`` in total per ``window_seconds``. A request is counted only
when both limits allow it. At most ``max_keys`` clients are tracked; when the
map is full, expired entries are pruned, and if it is still full the request
is refused (fails closed).

A client is keyed by ``HMAC-SHA256(process_key, host)[:16]`` under a random
key made per limiter instance and never persisted, so a key cannot be linked
back to an address after a restart. Neither the host nor the key is ever
logged, stored or put in an error. Limits multiply with worker processes.
"""

import hashlib
import hmac
import math
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable


class FeedbackRateLimiter:
    def __init__(
        self,
        per_client: int = 5,
        global_limit: int = 120,
        window_seconds: float = 600,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.per_client = per_client
        self.global_limit = global_limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._clock = clock
        self._process_key = secrets.token_bytes(32)
        self._clients: dict[bytes, deque[float]] = {}
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    def _key(self, client_host: str) -> bytes:
        return hmac.new(self._process_key, client_host.encode(), hashlib.sha256).digest()[:16]

    def _prune(self, entries: deque[float], now: float) -> None:
        while entries and now - entries[0] >= self.window_seconds:
            entries.popleft()

    def _prune_keys(self, now: float) -> None:
        for key in list(self._clients):
            entries = self._clients[key]
            self._prune(entries, now)
            if not entries:
                del self._clients[key]

    def tracked_keys(self) -> int:
        """How many clients are tracked (for tests)."""
        return len(self._clients)

    def check_and_consume(self, client_host: str) -> int | None:
        """``None`` and one unit consumed when allowed, else the Retry-After seconds (>= 1)."""
        with self._lock:
            now = self._clock()
            self._prune(self._global, now)
            key = self._key(client_host)
            entries = self._clients.get(key)
            if entries is not None:
                self._prune(entries, now)
            waits: list[float] = []
            if entries is None or not entries:
                if key not in self._clients and len(self._clients) >= self.max_keys:
                    self._prune_keys(now)
                    if len(self._clients) >= self.max_keys:
                        # The first tracked client to expire completely frees a slot.
                        waits.append(
                            min(e[-1] for e in self._clients.values()) + self.window_seconds - now
                        )
            elif len(entries) >= self.per_client:
                waits.append(entries[0] + self.window_seconds - now)
            if len(self._global) >= self.global_limit:
                waits.append(self._global[0] + self.window_seconds - now)
            if waits:
                return max(1, math.ceil(max(waits)))
            if entries is None:
                entries = self._clients[key] = deque()
            entries.append(now)
            self._global.append(now)
            return None


__all__ = ["FeedbackRateLimiter"]

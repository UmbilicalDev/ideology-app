"""feedback-admin Decision 5: the in-memory Operator session store (fake clock)."""

import hashlib

from ideology_app.admin.sessions import AdminSessionStore


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_create_get_and_remove() -> None:
    store = AdminSessionStore(clock=Clock())
    token, session = store.create("prueba")
    assert len(token) >= 43 and len(session.csrf_token) >= 43
    assert store.get(token) is session
    assert session.username == "prueba"
    # Only the token's SHA-256 is kept.
    assert session.token_hash == hashlib.sha256(token.encode()).digest()
    assert token not in repr(vars(store))
    assert store.get("unknown") is None
    assert store.get(None) is None
    assert store.get("") is None
    store.remove(token)
    assert store.get(token) is None


def test_idle_expiry_and_refresh() -> None:
    clock = Clock()
    store = AdminSessionStore(clock=clock)
    token, _ = store.create("prueba")
    clock.now += 1800
    assert store.get(token) is not None  # exactly 30 min: still alive, refreshed
    clock.now += 1800
    assert store.get(token) is not None
    clock.now += 1801
    assert store.get(token) is None
    assert len(store) == 0


def test_absolute_expiry_while_active() -> None:
    clock = Clock()
    store = AdminSessionStore(clock=clock)
    token, _ = store.create("prueba")
    for _ in range(16):  # 16 x 30 min = 8 h, active all along
        clock.now += 1800
        assert store.get(token) is not None
    clock.now += 1
    assert store.get(token) is None


def test_sign_in_replaces_the_carried_session() -> None:
    store = AdminSessionStore(clock=Clock())
    old, _ = store.create("prueba")
    new, _ = store.create("prueba", replacing=old)
    assert new != old
    assert store.get(old) is None
    assert store.get(new) is not None


def test_full_store_prunes_expired_then_evicts_the_oldest() -> None:
    clock = Clock()
    store = AdminSessionStore(max_sessions=3, clock=clock)
    first, _ = store.create("a")
    clock.now += 10
    second, _ = store.create("b")
    clock.now += 10
    third, _ = store.create("c")
    clock.now += 10
    fourth, _ = store.create("d")  # full: the oldest (first) goes
    assert len(store) == 3
    assert store.get(first) is None
    assert store.get(second) is not None  # refreshed at t=1030
    # At t=2825 third (last seen 1020) is idle for 1805 s, second and fourth for 1795 s.
    clock.now += 1795
    fifth, _ = store.create("e")
    # Full again: the expired third is pruned, so no live session is evicted.
    assert len(store) == 3
    assert store.get(third) is None
    assert store.get(second) is not None
    assert store.get(fourth) is not None
    assert store.get(fifth) is not None

"""feedback-api Scenario 5: the per-process abuse guard (Decision 8), with a fake clock."""

from ideology_app.feedback.rate_limit import FeedbackRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_per_client_limit_and_retry_after() -> None:
    clock = FakeClock()
    limiter = FeedbackRateLimiter(clock=clock)
    for _ in range(5):
        assert limiter.check_and_consume("10.0.0.1") is None
        clock.now += 10
    # The first request was at 1000; it leaves the window at 1600.
    assert limiter.check_and_consume("10.0.0.1") == 1600 - 1050
    # Another client is not affected.
    assert limiter.check_and_consume("10.0.0.2") is None
    clock.now = 1599.5
    assert limiter.check_and_consume("10.0.0.1") == 1  # rounded up, at least 1
    clock.now = 1600
    assert limiter.check_and_consume("10.0.0.1") is None
    assert limiter.check_and_consume("10.0.0.1") == 10


def test_allowed_again_after_the_window() -> None:
    clock = FakeClock()
    limiter = FeedbackRateLimiter(clock=clock)
    for _ in range(5):
        assert limiter.check_and_consume("h") is None
    assert limiter.check_and_consume("h") == 600
    clock.now += 600
    assert limiter.check_and_consume("h") is None


def test_refused_requests_consume_nothing() -> None:
    clock = FakeClock()
    limiter = FeedbackRateLimiter(per_client=1, global_limit=3, clock=clock)
    assert limiter.check_and_consume("a") is None
    for _ in range(10):
        assert limiter.check_and_consume("a") is not None
    # Only one unit of the global budget was used.
    assert limiter.check_and_consume("b") is None
    assert limiter.check_and_consume("c") is None
    assert limiter.check_and_consume("d") is not None


def test_global_limit() -> None:
    clock = FakeClock()
    limiter = FeedbackRateLimiter(clock=clock)
    for i in range(120):
        assert limiter.check_and_consume(f"client-{i % 30}") is None
        clock.now += 1
    assert limiter.check_and_consume("fresh") == 600 - 120
    clock.now = 1600
    assert limiter.check_and_consume("fresh") is None


def test_key_map_cap_prunes_then_fails_closed() -> None:
    clock = FakeClock()
    limiter = FeedbackRateLimiter(global_limit=100, max_keys=3, clock=clock)
    for host in ("a", "b", "c"):
        assert limiter.check_and_consume(host) is None
        clock.now += 100
    assert limiter.tracked_keys() == 3
    # Map full, nothing expired: a new client is refused until "a" expires.
    assert limiter.check_and_consume("d") == 1600 - 1300
    # A tracked client still gets its own budget.
    assert limiter.check_and_consume("b") is None
    clock.now = 1600
    assert limiter.check_and_consume("d") is None
    assert limiter.tracked_keys() == 3


def test_keys_are_keyed_hashes_not_addresses() -> None:
    limiter = FeedbackRateLimiter()
    limiter.check_and_consume("192.0.2.7")
    keys = list(limiter._clients)  # noqa: SLF001
    assert len(keys) == 1 and len(keys[0]) == 16
    assert b"192.0.2.7" not in keys[0]
    # A new limiter (a restart) has another process key: the keys do not match.
    other = FeedbackRateLimiter()
    other.check_and_consume("192.0.2.7")
    assert list(other._clients) != keys  # noqa: SLF001

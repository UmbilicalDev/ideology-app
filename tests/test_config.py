"""``config.source_refetch_interval`` (live-mode-url-refetch Scenario 4)."""

import datetime as dt

import pytest

from ideology_app import config
from ideology_app.config import ConfigError, source_refetch_interval

VAR = "SOURCE_REFETCH_INTERVAL_HOURS"


@pytest.mark.parametrize("raw", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_default_interval_is_six_hours(monkeypatch: pytest.MonkeyPatch, raw: str | None) -> None:
    if raw is None:
        monkeypatch.delenv(VAR, raising=False)
    else:
        monkeypatch.setenv(VAR, raw)

    assert source_refetch_interval() == dt.timedelta(hours=6)
    assert config.DEFAULT_SOURCE_REFETCH_INTERVAL_HOURS == 6


@pytest.mark.parametrize(("raw", "hours"), [("1", 1), (" 12 ", 12), ("168", 168)])
def test_interval_in_whole_hours(monkeypatch: pytest.MonkeyPatch, raw: str, hours: int) -> None:
    monkeypatch.setenv(VAR, raw)

    assert source_refetch_interval() == dt.timedelta(hours=hours)


@pytest.mark.parametrize("raw", ["0", "-1", "1.5", "6h", "+6", "seis", "٦"])
def test_invalid_interval_raises(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv(VAR, raw)

    with pytest.raises(ConfigError) as info:
        source_refetch_interval()
    assert str(info.value) == f"Invalid {VAR} {raw!r}; expected a positive integer"

"""LLM configuration, provider registry and the fake provider (offline)."""

import socket

import pytest
from pydantic import BaseModel

from ideology_app.config import (
    ConfigError,
    GenerationMode,
    LLMSettings,
    generation_mode,
    llm_settings,
)
from ideology_app.llm import (
    PROVIDERS,
    AnthropicProvider,
    FakeProvider,
    LLMConfigError,
    LLMError,
    LLMOutputError,
    LLMRequest,
    LLMResult,
    build_provider,
)

LLM_ENV_VARS = ("ANTHROPIC_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "GENERATION_MODE")


@pytest.fixture(autouse=True)
def _offline_and_clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real key or LLM settings leak in, and no socket can connect."""
    for name in LLM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is blocked in LLM tests")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


class DemoOutput(BaseModel):
    answer: str
    count: int


def demo_request(task: str = "demo") -> LLMRequest[DemoOutput]:
    return LLMRequest(task=task, system="You answer.", prompt="Say yes twice", schema=DemoOutput)


# Scenario 1: provider resolved from configuration


def test_build_provider_fake_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    provider = build_provider(llm_settings())
    assert isinstance(provider, FakeProvider)
    assert provider.name == "fake"
    assert provider.model == "fake-model"


def test_build_provider_anthropic_from_config_without_key_or_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-haiku-5-5")
    provider = build_provider(llm_settings())
    assert isinstance(provider, AnthropicProvider)
    assert provider.name == "anthropic"
    assert provider.model == "claude-haiku-5-5"
    assert provider._client is None  # no client created, no key read


def test_registry_matches_default_models() -> None:
    from ideology_app.config import DEFAULT_MODELS

    assert set(PROVIDERS) == set(DEFAULT_MODELS) == {"anthropic", "fake"}


# Scenario 2: defaults, trimming, case-insensitivity


def test_defaults_when_unset() -> None:
    assert llm_settings() == LLMSettings(provider="anthropic", model="claude-sonnet-5-5")
    assert generation_mode() is GenerationMode.PRECOMPUTED


def test_empty_values_count_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setenv("LLM_MODEL", "   ")
    monkeypatch.setenv("GENERATION_MODE", "")
    assert llm_settings() == LLMSettings(provider="anthropic", model="claude-sonnet-5-5")
    assert generation_mode() is GenerationMode.PRECOMPUTED


def test_values_trimmed_and_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "  FaKe ")
    monkeypatch.setenv("GENERATION_MODE", " LIVE ")
    assert llm_settings() == LLMSettings(provider="fake", model="fake-model")
    assert generation_mode() is GenerationMode.LIVE


def test_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", " claude-opus-5-5 ")
    assert llm_settings() == LLMSettings(provider="anthropic", model="claude-opus-5-5")


# Scenario 3: invalid configuration fails clearly


def test_unknown_provider_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(ConfigError, match="anthropic, fake"):
        llm_settings()


def test_unknown_generation_mode_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENERATION_MODE", "sometimes")
    with pytest.raises(ConfigError, match="precomputed, live"):
        generation_mode()


def test_config_error_is_value_error() -> None:
    assert issubclass(ConfigError, ValueError)


def test_build_provider_unregistered_name_raises_llm_config_error() -> None:
    with pytest.raises(LLMConfigError, match="anthropic, fake") as info:
        build_provider(LLMSettings(provider="openai", model="gpt"))
    assert isinstance(info.value, LLMError)
    assert isinstance(info.value, ConfigError)


# Scenario 4: the fake returns deterministic structured output


def test_fake_returns_deterministic_structured_output() -> None:
    provider = FakeProvider({"demo": {"answer": "yes", "count": 2}})
    first = provider.generate(demo_request())
    second = provider.generate(demo_request())
    assert first == second
    assert isinstance(first, LLMResult)
    assert first.output == DemoOutput(answer="yes", count=2)
    assert first.provider == "fake"
    assert first.model == "fake-model"
    assert isinstance(first.input_tokens, int) and first.input_tokens == 5
    assert isinstance(first.output_tokens, int) and first.output_tokens > 0
    assert provider.calls == [demo_request(), demo_request()]


def test_fake_accepts_schema_instance_and_callable() -> None:
    def respond(request: LLMRequest[DemoOutput]) -> dict[str, object]:
        return {"answer": request.prompt, "count": len(provider.calls)}

    provider = FakeProvider(
        {"instance": DemoOutput(answer="no", count=0), "callable": respond}
    )
    assert provider.generate(demo_request("instance")).output == DemoOutput(answer="no", count=0)
    assert provider.generate(demo_request("callable")).output == DemoOutput(
        answer="Say yes twice", count=2
    )


def test_fake_callable_may_return_instance() -> None:
    provider = FakeProvider({"demo": lambda request: DemoOutput(answer="ok", count=1)})
    assert provider.generate(demo_request()).output == DemoOutput(answer="ok", count=1)


def test_fake_custom_model() -> None:
    provider = FakeProvider({"demo": {"answer": "yes", "count": 2}}, model="other")
    assert provider.generate(demo_request()).model == "other"


# Scenario 5: the fake fails like a real provider


def test_fake_missing_task_raises_llm_error() -> None:
    provider = FakeProvider({"demo": {"answer": "yes", "count": 2}})
    with pytest.raises(LLMError, match="'missing'"):
        provider.generate(demo_request("missing"))
    assert len(provider.calls) == 1


def test_fake_schema_mismatch_raises_output_error() -> None:
    provider = FakeProvider({"demo": {"answer": "yes", "count": "many"}})
    with pytest.raises(LLMOutputError, match="DemoOutput"):
        provider.generate(demo_request())

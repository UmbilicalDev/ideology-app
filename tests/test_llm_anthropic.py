"""Anthropic adapter through an injected client with ``httpx2.MockTransport`` (offline)."""

import json
import socket
from collections.abc import Callable, Iterator
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from ideology_app.llm import (
    AnthropicProvider,
    LLMConfigError,
    LLMError,
    LLMOutputError,
    LLMProviderError,
    LLMRequest,
)
from ideology_app.pipeline.generation import reduce_request
from ideology_app.pipeline.positions import findings_request
from ideology_app.pipeline.prompts import StatementDraft

LLM_ENV_VARS = ("ANTHROPIC_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "GENERATION_MODE")
SECRET = "sk-secret-test"


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


REQUEST = LLMRequest(task="demo", system="S", prompt="P", schema=DemoOutput, max_tokens=256)

Handler = Callable[[httpx2.Request], httpx2.Response]


def message_response(text: str, *, stop_reason: str = "end_turn") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": [{"type": "text", "text": text}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 17, "output_tokens": 9},
        },
    )


def error_response(status: int, error_type: str) -> httpx2.Response:
    return httpx2.Response(
        status, json={"type": "error", "error": {"type": error_type, "message": "nope"}}
    )


@pytest.fixture
def mock_provider() -> Iterator[Callable[[Handler], tuple[AnthropicProvider, list[httpx2.Request]]]]:
    """Build an ``AnthropicProvider`` whose client answers through a handler."""
    http_clients: list[httpx2.Client] = []

    def make(handler: Handler) -> tuple[AnthropicProvider, list[httpx2.Request]]:
        captured: list[httpx2.Request] = []

        def record(request: httpx2.Request) -> httpx2.Response:
            captured.append(request)
            return handler(request)

        http_client = httpx2.Client(transport=httpx2.MockTransport(record))
        http_clients.append(http_client)
        client = anthropic.Anthropic(api_key="test-key", http_client=http_client, max_retries=0)
        return AnthropicProvider(model="claude-haiku-5-5", client=client), captured

    yield make
    for http_client in http_clients:
        http_client.close()


# Scenario 6: structured-output request through an injected client


def test_generate_sends_structured_output_request(mock_provider: Any) -> None:
    provider, captured = mock_provider(
        lambda request: message_response('{"answer": "yes", "count": 2}')
    )
    result = provider.generate(REQUEST)

    assert len(captured) == 1
    assert captured[0].url.path == "/v1/messages"
    body = json.loads(captured[0].content)
    assert body["model"] == "claude-haiku-5-5"
    assert body["max_tokens"] == 256
    assert body["system"] == "S"
    assert body["messages"] == [{"role": "user", "content": "P"}]
    output_format = body["output_config"]["format"]
    assert output_format["type"] == "json_schema"
    assert set(output_format["schema"]["properties"]) == {"answer", "count"}
    assert set(output_format["schema"]["required"]) == {"answer", "count"}

    assert result.output == DemoOutput(answer="yes", count=2)
    assert result.provider == "anthropic"
    assert result.model == "claude-haiku-5-5"
    assert (result.input_tokens, result.output_tokens) == (17, 9)


def test_injected_client_is_not_closed_by_provider(mock_provider: Any) -> None:
    provider, _ = mock_provider(lambda request: message_response('{"answer": "a", "count": 1}'))
    with provider:
        provider.generate(REQUEST)
    # Still usable: the provider does not own an injected client.
    assert provider.generate(REQUEST).output == DemoOutput(answer="a", count=1)


# Scenario 7: error mapping


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(lambda: message_response("not json"), id="invalid-json"),
        pytest.param(lambda: message_response('{"answer": "yes"}'), id="schema-mismatch"),
        pytest.param(
            lambda: message_response('{"answer": "yes", "count": 1}', stop_reason="refusal"),
            id="refusal",
        ),
        pytest.param(
            lambda: message_response("I can't help with that.", stop_reason="refusal"),
            id="refusal-plain-text",
        ),
    ],
)
def test_bad_output_raises_output_error(mock_provider: Any, response: Any) -> None:
    provider, _ = mock_provider(lambda request: response())
    with pytest.raises(LLMOutputError):
        provider.generate(REQUEST)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(401, "authentication_error"), (529, "overloaded_error")],
)
def test_http_errors_raise_provider_error(mock_provider: Any, status: int, error_type: str) -> None:
    provider, captured = mock_provider(lambda request: error_response(status, error_type))
    with pytest.raises(LLMProviderError, match=str(status)) as info:
        provider.generate(REQUEST)
    assert isinstance(info.value.__cause__, anthropic.APIError)
    assert len(captured) == 1  # max_retries=0


# Scenario 8: missing API key fails lazily and safely


def test_missing_key_fails_lazily_before_any_socket() -> None:
    provider = AnthropicProvider(model="claude-haiku-5-5")
    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY"):
        provider.generate(REQUEST)
    assert provider._client is None


def test_blank_env_key_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider(model="m").generate(REQUEST)


def test_key_never_in_repr_or_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AnthropicProvider(model="claude-haiku-5-5", api_key=SECRET, max_retries=0)
    assert SECRET not in repr(provider)
    assert repr(provider) == "AnthropicProvider(model='claude-haiku-5-5')"
    # The self-created client hits the socket guard -> connection error -> LLMProviderError.
    with provider, pytest.raises(LLMError) as info:
        provider.generate(REQUEST)
    assert isinstance(info.value, LLMProviderError)
    assert SECRET not in str(info.value)
    assert SECRET not in repr(info.value)
    assert "network access is blocked" in " ".join(map(str, cause_chain(info.value)))


def cause_chain(exc: BaseException | None) -> list[BaseException]:
    chain = []
    while exc is not None:
        chain.append(exc)
        exc = exc.__cause__ or exc.__context__
    return chain


def test_env_key_creates_owned_client_that_close_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    provider = AnthropicProvider(model="m", max_retries=0)
    with provider, pytest.raises(LLMProviderError) as info:
        provider.generate(REQUEST)
    assert SECRET not in str(info.value)
    assert provider._client is None  # closed and released on exit


# pipeline-output-bounds: bounded schemas through the Anthropic SDK. The SDK
# does not send minimum, maximum, maxItems or a minItems above 1 as constraints:
# it appends them to the field description as hints and validates on the client.


def _sent_schema(request: httpx2.Request) -> dict[str, Any]:
    return json.loads(request.content)["output_config"]["format"]["schema"]


def test_bounded_findings_request_sends_the_bound_as_a_hint_and_validates(
    mock_provider: Any,
) -> None:
    finding = {"statement": 101, "value": 1, "quote": "Uno.", "page": 1}
    provider, captured = mock_provider(
        lambda request: message_response(json.dumps({"findings": [finding]}))
    )

    with pytest.raises(LLMOutputError) as info:
        provider.generate(findings_request("[1] A", "[página 1]\nUno.", 30))

    assert str(info.value).startswith(
        "Anthropic output for task 'position_findings' does not match FindingList: "
    )
    statement = _sent_schema(captured[0])["$defs"]["Finding"]["properties"]["statement"]
    assert statement["type"] == "integer"
    assert "maximum: 30" in statement["description"]
    assert "maximum" not in statement


def test_bounded_statement_count_is_validated_on_the_client(mock_provider: Any) -> None:
    drafts = [{"text": f"Afirmación {n}.", "topic": "housing"} for n in range(38)]
    provider, captured = mock_provider(
        lambda request: message_response(json.dumps({"statements": drafts}))
    )

    with pytest.raises(LLMOutputError, match="does not match StatementSet"):
        provider.generate(reduce_request([StatementDraft(text="Alfa.", topic="housing")]))

    statements = _sent_schema(captured[0])["properties"]["statements"]
    assert "maxItems: 35" in statements["description"]
    assert "minItems: 25" in statements["description"]


def test_in_range_bounded_output_passes(mock_provider: Any) -> None:
    finding = {"statement": 30, "value": -2, "quote": "Uno.", "page": 1}
    provider, _ = mock_provider(
        lambda request: message_response(json.dumps({"findings": [finding]}))
    )

    result = provider.generate(findings_request("[1] A", "[página 1]\nUno.", 30))

    assert [f.statement for f in result.output.findings] == [30]

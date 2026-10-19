"""Provider-neutral request, result, protocol and errors for LLM calls."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from ideology_app.config import ConfigError


@dataclass(frozen=True)
class LLMRequest[T: BaseModel]:
    """One prompt whose answer must validate against ``schema``.

    ``task`` is a stable key for the kind of call (e.g. ``"generate_statements"``);
    the fake provider uses it to pick a canned response.
    """

    task: str
    system: str
    prompt: str
    schema: type[T]
    max_tokens: int = 4096


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    """A validated structured answer plus what a Pipeline Run needs to record."""

    output: T
    provider: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMProvider(Protocol):
    """Anything that turns an ``LLMRequest`` into a validated ``LLMResult``."""

    name: str
    model: str

    def generate[T: BaseModel](self, request: LLMRequest[T]) -> LLMResult[T]: ...


class LLMError(Exception):
    """Base class for every LLM failure."""


class LLMConfigError(LLMError, ConfigError):
    """The provider is unknown or not configured (e.g. a missing API key)."""


class LLMOutputError(LLMError):
    """The model answered, but not with output that matches the schema."""


class LLMProviderError(LLMError):
    """The provider call failed (HTTP error, connection error, overload...)."""

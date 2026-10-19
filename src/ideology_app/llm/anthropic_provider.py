"""Anthropic adapter: structured output through ``messages.parse``.

This is the only module that imports the Anthropic SDK. The API key is read
lazily, on the first ``generate``, and never appears in reprs or error messages.
"""

import os
from types import TracebackType
from typing import Self

import anthropic
from pydantic import BaseModel, ValidationError

from ideology_app.llm.base import (
    LLMConfigError,
    LLMOutputError,
    LLMProviderError,
    LLMRequest,
    LLMResult,
)

API_KEY_ENV = "ANTHROPIC_API_KEY"


class AnthropicProvider:
    """``LLMProvider`` backed by the Anthropic Messages API."""

    name = "anthropic"

    def __init__(
        self,
        model: str,
        *,
        client: anthropic.Anthropic | None = None,
        api_key: str | None = None,
        max_retries: int = 2,
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self._client = client
        self._owns_client = False
        self._api_key = api_key
        self._max_retries = max_retries
        self._timeout = timeout

    def __repr__(self) -> str:
        return f"AnthropicProvider(model={self.model!r})"

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            api_key = self._api_key or os.environ.get(API_KEY_ENV, "").strip()
            if not api_key:
                raise LLMConfigError(f"{API_KEY_ENV} is not set")
            self._client = anthropic.Anthropic(
                api_key=api_key, max_retries=self._max_retries, timeout=self._timeout
            )
            self._owns_client = True
        return self._client

    def generate[T: BaseModel](self, request: LLMRequest[T]) -> LLMResult[T]:
        client = self._get_client()
        try:
            message = client.messages.parse(
                model=self.model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=[{"role": "user", "content": request.prompt}],
                output_format=request.schema,
            )
        except ValidationError as exc:
            raise LLMOutputError(
                f"Anthropic output for task {request.task!r} does not match "
                f"{request.schema.__name__}: {exc.error_count()} validation error(s)"
            ) from exc
        except anthropic.APIError as exc:
            status = getattr(exc, "status_code", None)
            detail = f" (HTTP {status})" if status is not None else ""
            raise LLMProviderError(
                f"Anthropic call for task {request.task!r} failed: "
                f"{type(exc).__name__}{detail}"
            ) from exc
        if message.stop_reason == "refusal":
            raise LLMOutputError(f"Anthropic refused task {request.task!r}")
        output = message.parsed_output
        if output is None:
            raise LLMOutputError(
                f"Anthropic returned no structured output for task {request.task!r} "
                f"(stop_reason={message.stop_reason!r})"
            )
        return LLMResult(
            output=output,
            provider=self.name,
            model=self.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )

    def close(self) -> None:
        """Close the client if this provider created it; injected clients are left open."""
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None
            self._owns_client = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

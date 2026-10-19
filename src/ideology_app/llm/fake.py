"""Deterministic in-memory provider used by every test."""

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from ideology_app.llm.base import LLMError, LLMOutputError, LLMRequest, LLMResult

type FakeResponse = (
    Mapping[str, Any] | BaseModel | Callable[[LLMRequest[Any]], Mapping[str, Any] | BaseModel]
)


class FakeProvider:
    """Returns canned responses keyed by ``LLMRequest.task``.

    A response may be a dict, a schema instance, or a callable that receives the
    request and returns either. No randomness, clock or I/O is used, so the same
    request always gives the same result. Every request is appended to ``calls``.
    """

    name = "fake"

    def __init__(
        self,
        responses: Mapping[str, FakeResponse] | None = None,
        model: str = "fake-model",
    ) -> None:
        self.responses: dict[str, FakeResponse] = dict(responses or {})
        self.model = model
        self.calls: list[LLMRequest[Any]] = []

    def __repr__(self) -> str:
        return f"FakeProvider(model={self.model!r}, tasks={sorted(self.responses)!r})"

    def generate[T: BaseModel](self, request: LLMRequest[T]) -> LLMResult[T]:
        self.calls.append(request)
        if request.task not in self.responses:
            raise LLMError(f"FakeProvider has no response for task {request.task!r}")
        response = self.responses[request.task]
        if callable(response):
            response = response(request)
        if isinstance(response, BaseModel):
            response = response.model_dump(mode="json")
        try:
            output = request.schema.model_validate(response)
        except ValidationError as exc:
            raise LLMOutputError(
                f"FakeProvider response for task {request.task!r} does not match "
                f"{request.schema.__name__}: {exc.error_count()} validation error(s)"
            ) from exc
        return LLMResult(
            output=output,
            provider=self.name,
            model=self.model,
            input_tokens=len(f"{request.system} {request.prompt}".split()),
            output_tokens=len(output.model_dump_json().split()),
        )

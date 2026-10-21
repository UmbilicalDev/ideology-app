"""Pipeline Run checkpoint: record every LLM call and reuse them on a resume.

``CheckpointProvider`` wraps the injected provider for one run. Each successful
call is inserted into ``pipeline_run_calls`` in its own commit as soon as it
returns, so a run that stops halfway keeps what it paid for. A run queued with
``resumed_from_run_id`` first looks for an unused recorded call of that run
with the same ``request_hash``; on a hit the stored output is re-validated
against the request schema and returned with zero tokens, without calling the
provider. Outputs are stored and returned exactly as validated (never edited).

Depends only on ``llm.base``, ``models`` and ``db``; generation and extraction
see an ordinary ``LLMProvider``.
"""

import hashlib
import json
from collections import defaultdict, deque
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, func, select

from ideology_app.db import session_scope
from ideology_app.llm.base import LLMProvider, LLMRequest, LLMResult
from ideology_app.models import PipelineRunCall


def request_hash(provider: str, model: str, request: LLMRequest[Any]) -> str:
    """SHA-256 of everything that determines an answer: provider, model and request."""
    payload = {
        "provider": provider,
        "model": model,
        "task": request.task,
        "system": request.system,
        "prompt": request.prompt,
        "schema": request.schema.model_json_schema(),
        "max_tokens": request.max_tokens,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def count_recorded_calls(engine: Engine, run_id: int) -> int:
    """How many LLM calls a run has recorded so far."""
    with session_scope(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(PipelineRunCall)
            .where(PipelineRunCall.pipeline_run_id == run_id)
        ) or 0


class CheckpointProvider:
    """``LLMProvider`` that records each call of run ``run_id`` and reuses a resumed run's."""

    def __init__(
        self,
        inner: LLMProvider,
        engine: Engine,
        run_id: int,
        resumed_from_run_id: int | None = None,
    ) -> None:
        self.name = inner.name
        self.model = inner.model
        self._inner = inner
        self._engine = engine
        self._run_id = run_id
        self._sequence = 0
        self._reusable: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        if resumed_from_run_id is not None:
            with session_scope(engine) as session:
                rows = session.execute(
                    select(PipelineRunCall.request_hash, PipelineRunCall.output)
                    .where(PipelineRunCall.pipeline_run_id == resumed_from_run_id)
                    .order_by(PipelineRunCall.sequence)
                ).all()
            for hash_, output in rows:
                self._reusable[hash_].append(output)
        self.reusable_calls = sum(len(q) for q in self._reusable.values())

    def __repr__(self) -> str:
        return f"CheckpointProvider({self._inner!r}, run_id={self._run_id})"

    def _reuse[T: BaseModel](self, hash_: str, request: LLMRequest[T]) -> T | None:
        queue = self._reusable.get(hash_)
        while queue:
            stored = queue.popleft()
            try:
                return request.schema.model_validate(stored)
            except ValidationError:
                continue  # A stored output that no longer validates is a miss.
        return None

    def _record(self, hash_: str, task: str, result: LLMResult[Any], reused: bool) -> None:
        self._sequence += 1
        with session_scope(self._engine) as session:
            session.add(
                PipelineRunCall(
                    pipeline_run_id=self._run_id,
                    sequence=self._sequence,
                    task=task,
                    request_hash=hash_,
                    output=result.output.model_dump(mode="json"),
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    reused=reused,
                )
            )

    def generate[T: BaseModel](self, request: LLMRequest[T]) -> LLMResult[T]:
        hash_ = request_hash(self.name, self.model, request)
        output = self._reuse(hash_, request)
        if output is not None:
            result = LLMResult(
                output=output,
                provider=self.name,
                model=self.model,
                input_tokens=0,
                output_tokens=0,
            )
            self._record(hash_, request.task, result, reused=True)
            return result
        result = self._inner.generate(request)
        self._record(hash_, request.task, result, reused=False)
        return result


__all__ = ["CheckpointProvider", "count_recorded_calls", "request_hash"]

"""Shared helpers for the proposal-conflicts tests (FakeProvider only, bundles in tmp_path).

Party ``P`` runs in 28 and 31 and lists ``a.md`` (all its Constituencies, 3
Proposals) and ``b.md`` (28 only, 2 Proposals): one overlap in 28. With
``shared=True`` Party ``Q`` (28 only) lists the same two files, so its overlap
has the same content-hash pair. Every extracted Proposal has the categories
``housing`` and ``economy``, so each overlap is compared in two buckets (two
requests).
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from bundle_factory import CandidatureSpec, DocumentSpec
from proposal_fixtures import import_dir, item, keep_all, measure, pages_in, small_page, write_v2
from sqlalchemy import Engine

from ideology_app.llm import FakeProvider, LLMProviderError, LLMRequest
from ideology_app.proposals import store

P = CandidatureSpec("P", "Partido P", ["28", "31"])
Q = CandidatureSpec("Q", "Partido Q", ["28"])
CATEGORIES = ("housing", "economy")
EXPLANATION = "A rebaja el alquiler y B lo congela."


def documents(*, shared: bool = False, joint: Sequence[str] = ()) -> list[DocumentSpec]:
    parties = ["P", "Q"] if shared else ["P"]
    return [
        DocumentSpec("a.md", "P", [small_page(1, 3)], parties,
                     joint_for=["P"] if "a.md" in joint else None),
        DocumentSpec("b.md", "P", [small_page(1, 2)], parties, ["28"],
                     joint_for=["P"] if "b.md" in joint else None),
    ]


def extraction_fake() -> FakeProvider:
    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        count = 3 if "Medida 3" in request.prompt else 2
        return {
            "proposals": [
                item(measure(page, k), page, CATEGORIES)
                for page in pages_in(request)
                for k in range(1, count + 1)
            ]
        }

    return FakeProvider({"proposal_extraction": respond})


def conflict_fake(
    contradictions: Sequence[dict[str, Any]] = (),
    *,
    fail_on_call: int | None = None,
    model: str = "fake-model",
) -> FakeProvider:
    """Answers every conflict request with ``contradictions`` (1-based request order)."""
    provider: FakeProvider

    def respond(request: LLMRequest[Any]) -> dict[str, Any]:
        if fail_on_call is not None and len(provider.calls) == fail_on_call:
            raise LLMProviderError("provider overloaded (529)")
        return {"contradictions": list(contradictions)}

    provider = FakeProvider({"proposal_conflict_check": respond}, model=model)
    return provider


FLAG = {"a": 1, "b": 2, "explanation": EXPLANATION}


def setup(
    root: Path,
    engine: Engine,
    *,
    shared: bool = False,
    joint: Sequence[str] = (),
    extract: bool = True,
    min_proposals: int = 1,
) -> Path:
    """Write, import, keep every document and (by default) extract the Proposals."""
    parties = [P, Q] if shared else [P]
    directory = write_v2(root, parties, documents(shared=shared, joint=joint))
    import_dir(engine, directory)
    keep_all(directory, min_proposals=min_proposals)
    if extract:
        extract_all(engine, directory)
    return directory


def extract_all(engine: Engine, directory: Path) -> None:
    provider = extraction_fake()
    plan = store.prepare_extraction(engine, directory, provider)
    summary = store.execute_plan(engine, provider, plan)
    assert summary.error is None and not summary.failed and not summary.stopped


def collector() -> tuple[list[str], Callable[..., None]]:
    lines: list[str] = []

    def echo(line: str, err: bool = False) -> None:
        lines.append(f"Error-stream: {line}" if err else line)

    return lines, echo

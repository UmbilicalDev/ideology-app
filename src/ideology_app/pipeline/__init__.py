"""The AI pipeline: Pipeline Runs that turn Source Documents into a Dataset Version.

Depends on ``models``, ``elections`` (errors) and ``llm.base`` only; a provider
is always injected, never built here.
"""

from ideology_app.pipeline.generation import (
    CHUNK_MAX_CHARS,
    MAX_LLM_CALLS_PER_RUN,
    NO_CANDIDATES_REASON,
    DocumentPages,
    GenerationError,
    Usage,
    build_chunks,
    generate_statements,
)
from ideology_app.pipeline.prompts import (
    GENERATE_STATEMENTS,
    PROMPT_VERSIONS,
    PROMPTS,
    STATEMENT_CANDIDATES,
    TARGET_STATEMENT_COUNT,
    TOPICS,
    CandidateList,
    PromptSpec,
    StatementDraft,
    StatementSet,
)
from ideology_app.pipeline.runs import (
    RunOutcome,
    execute_run,
    get_dataset_version,
    list_runs,
    queue_run,
)

__all__ = [
    "CHUNK_MAX_CHARS",
    "GENERATE_STATEMENTS",
    "MAX_LLM_CALLS_PER_RUN",
    "NO_CANDIDATES_REASON",
    "PROMPTS",
    "PROMPT_VERSIONS",
    "STATEMENT_CANDIDATES",
    "TARGET_STATEMENT_COUNT",
    "TOPICS",
    "CandidateList",
    "DocumentPages",
    "GenerationError",
    "PromptSpec",
    "RunOutcome",
    "StatementDraft",
    "StatementSet",
    "Usage",
    "build_chunks",
    "execute_run",
    "generate_statements",
    "get_dataset_version",
    "list_runs",
    "queue_run",
]

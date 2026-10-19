# Feature Implementation Spec: Configurable LLM provider with a fake for tests

## Source Feature

- `id`: llm-provider-abstraction
- `area`: ai
- `depends_on`: bootstrap-app-skeleton (accepted)
- `status`: not_started (at planning time)
- `source`: `feature_list.json`

## Goal

Give the AI pipeline one small interface for "send a prompt, get back a validated structured object". Configuration picks the provider and model, so no code branches on them. The feature ships two implementations. A deterministic `FakeProvider` is used by every test. An `AnthropicProvider` uses the Anthropic SDK's structured output (`messages.parse(..., output_format=<pydantic model>)`). The Generation Mode setting is also read from configuration here as a typed value, so later features use the same config path.

Each result carries the provider name, the model and the token usage. The future Pipeline Run record (`docs/domain-model.md`) can then store them without knowing which provider ran.

## Non-Goals

- No prompts, no Statement or Party Position schemas, no pipeline code. Those belong to `pipeline-generate-statements` and `pipeline-extract-positions`.
- No Pipeline Run table, no migration, no prompt versioning, no cost estimate in currency. Only raw token counts are returned.
- No behaviour for `live` mode. This feature only parses `GENERATION_MODE`.
- No OpenAI or local-model adapter. The registry must make adding one a single entry.
- No CLI command, HTTP endpoint or UI. Do not edit `cli.py` or `main.py`; a parallel branch may touch `cli.py`.
- No streaming, tool use, batching, caching or retry logic of our own. The SDK's built-in `max_retries` is enough.
- No fixture-file loader for the fake (e.g. `LLM_FAKE_FIXTURES`). Pipeline features add one if they need it.

## Job Story

When I (the Operator, or a later pipeline feature) need structured output from an LLM,
I want to get a provider from configuration and call one typed method,
so I can switch providers or models by changing env vars, and tests stay offline and deterministic.

## Users And Permissions

- Operator: sets `LLM_PROVIDER`, `LLM_MODEL`, `GENERATION_MODE` and `ANTHROPIC_API_KEY` in the environment. There is no other surface.
- Voters: not involved.

## Acceptance Scenarios

### Scenario 1: Provider resolved from configuration

Given `LLM_PROVIDER=fake` and `LLM_MODEL` is unset
When `build_provider(llm_settings())` is called
Then it returns a `FakeProvider` with `name == "fake"` and `model == "fake-model"`.
And given `LLM_PROVIDER=anthropic` and `LLM_MODEL=claude-haiku-5-5`, it returns an `AnthropicProvider` with that model. No API key is read and no client or network connection is created.

### Scenario 2: Defaults

Given none of `LLM_PROVIDER`, `LLM_MODEL` or `GENERATION_MODE` is set
When the settings are read
Then the provider is `anthropic`, the model is `claude-sonnet-5-5` and the Generation Mode is `GenerationMode.PRECOMPUTED`.
Values are trimmed and matched case-insensitively. An empty string counts as unset.

### Scenario 3: Invalid configuration fails clearly

Given `LLM_PROVIDER=openai`, or `GENERATION_MODE=sometimes`
When the settings are read or the provider is built
Then `ideology_app.config.ConfigError` (a `ValueError`) is raised from the settings reader. `build_provider` given an unregistered name raises `LLMConfigError`, which subclasses both `LLMError` and `ConfigError`. Each message lists the supported values (`anthropic, fake` / `precomputed, live`).

### Scenario 4: The fake returns deterministic structured output

Given a `FakeProvider` whose responses are `{"demo": {"answer": "yes", "count": 2}}` and a request with `task="demo"` and `schema=DemoOutput` (a pydantic model)
When `generate(request)` is called twice
Then both results are equal. `result.output` is a `DemoOutput` instance, `result.provider == "fake"`, `result.model == "fake-model"`, the token counts are deterministic ints, and `provider.calls` holds both requests in order.
A response can be given as a dict, as a schema instance, or as a callable `(LLMRequest) -> dict | BaseModel`.

### Scenario 5: The fake fails like a real provider

Given a `FakeProvider` with no response for task `"missing"`, or with a canned dict that does not match the schema
When `generate` is called
Then it raises `LLMError` (missing task, message names the task) or `LLMOutputError` (schema mismatch).

### Scenario 6: Anthropic adapter sends a structured-output request through an injected client

Given an `AnthropicProvider(model="claude-haiku-5-5", client=<anthropic.Anthropic with api_key="test-key" and an httpx2.MockTransport http_client, max_retries=0>)`
When `generate(LLMRequest(task="demo", system="S", prompt="P", schema=DemoOutput, max_tokens=256))` is called
Then the single captured HTTP request goes to `/v1/messages`. Its JSON body has `model == "claude-haiku-5-5"`, `max_tokens == 256`, `system == "S"`, `messages == [{"role": "user", "content": "P"}]` and `output_config.format.type == "json_schema"` with the schema of `DemoOutput`. The result's `output` is the parsed `DemoOutput`, `provider == "anthropic"`, and `input_tokens`/`output_tokens` come from the response `usage`.

### Scenario 7: Anthropic adapter error mapping

Given the same mock setup
When the mocked response text is not valid JSON or does not match the schema, or `stop_reason == "refusal"`
Then `LLMOutputError` is raised.
When the mock returns HTTP 401 or 529
Then `LLMProviderError` is raised, chained from the SDK's `anthropic.APIError`.

### Scenario 8: Missing API key fails lazily and safely

Given `ANTHROPIC_API_KEY` is unset and no client is injected
When an `AnthropicProvider` is constructed, then `generate` is called
Then construction succeeds. `generate` raises `LLMConfigError` naming `ANTHROPIC_API_KEY`, before any socket is opened.
And given `api_key="sk-secret-test"`, neither `repr(provider)` nor any `LLMError` message contains the key.

### Scenario 9: Tests are offline

Given the LLM test module's autouse guard, which makes `socket.socket.connect` and `socket.create_connection` raise, and which unsets `ANTHROPIC_API_KEY`, `LLM_PROVIDER`, `LLM_MODEL` and `GENERATION_MODE`
When the whole suite runs via `CI=true ./init.sh`
Then every test passes (49 existing + new), with no warnings (`filterwarnings = ["error"]`) and no real key in the environment of any LLM test.

## Repository Research

### Files Inspected

- `AGENTS.md`: invariants "tests never call a real LLM" and "provider and Generation Mode are configuration".
- `PROGRESS.md`, `feature_list.json`: feature entry, verification items; baseline 49 tests on Python 3.15.
- `CONTEXT.md`: Generation Mode definition (`precomputed` / `live`).
- `docs/technical-discovery.md`: config table (`LLM_PROVIDER` / model, `GENERATION_MODE` default `precomputed`), and the provider/model to record per Pipeline Run.
- `docs/domain-model.md`, `docs/build-brief.md`: Pipeline Run records provider, model, prompt versions, Generation Mode. Success criterion: "switching the LLM provider or Generation Mode is a configuration change".
- `ARCHITECTURE.md`, `CONSTRAINTS.md`: layout, dependency direction, warnings-as-errors gate.
- `pyproject.toml`: dependencies; `httpx2` and `pydantic` 2.14 are already in `.venv` (pydantic via fastapi).
- `src/ideology_app/config.py`: env-reading pattern (`os.environ.get(...) or DEFAULT`).
- `tests/conftest.py`: autouse env-safety fixture pattern.
- Throwaway venv outside the repo (Python 3.15, `anthropic` 1.15.0): `Anthropic()` constructs without a key. `messages.parse(model, max_tokens, system, messages, output_format=Model)` sends `output_config={"format": {"type": "json_schema", "schema": ...}}` and returns `ParsedMessage` with `.parsed_output`, `.usage.input_tokens/.output_tokens`, `.stop_reason`, `.model`. Invalid JSON or schema mismatch raises `pydantic.ValidationError`. HTTP errors raise `anthropic.APIStatusError` subclasses (`AuthenticationError`, `OverloadedError`), all `anthropic.APIError`. `anthropic` depends on `httpx2<3,>=2`. A `httpx2.Client(transport=httpx2.MockTransport(handler))` passed as `http_client=` works offline and is clean under `-W error -X dev`.

### Existing Patterns To Follow

- Configuration readers are plain functions in `ideology_app.config`; tests use `monkeypatch.setenv/delenv`.
- Typed domain errors in a small hierarchy (see `ElectionsError` in `elections.py`).
- Close every resource you open (`CONSTRAINTS.md`); `ResourceWarning` fails the gate.
- Tests are flat in `tests/`, named `test_<module>.py`.

### Current Gaps

- No `ideology_app.llm` package, no `anthropic` dependency, no LLM or Generation Mode settings.

## Technical Approach

Create the package `src/ideology_app/llm/`:

- `base.py`:
  - `LLMRequest[T: BaseModel]`, a frozen dataclass with `task: str` (stable key, e.g. `"generate_statements"`), `system: str`, `prompt: str`, `schema: type[T]` and `max_tokens: int = 4096`.
  - `LLMResult[T]`, a frozen dataclass with `output: T`, `provider: str`, `model: str`, `input_tokens: int` and `output_tokens: int`.
  - `LLMProvider`, a `typing.Protocol` with attributes `name: str` and `model: str` and the method `generate(request: LLMRequest[T]) -> LLMResult[T]`.
  - Errors: `LLMError(Exception)`, with the subclasses `LLMConfigError`, `LLMOutputError` and `LLMProviderError`.
- `fake.py`: `FakeProvider(responses: Mapping[str, dict | BaseModel | Callable[[LLMRequest], dict | BaseModel]] | None = None, model: str = "fake-model")`.
  - It validates each response with `request.schema.model_validate` and turns `ValidationError` into `LLMOutputError`.
  - It records `self.calls`.
  - `input_tokens = len((system + " " + prompt).split())`; `output_tokens = len(output.model_dump_json().split())`.
  - It uses no randomness, clock or I/O.
- `anthropic_provider.py`. Do not call the module `anthropic.py`, so it does not shadow the SDK when read.
  - The class is `AnthropicProvider(model: str, *, client: anthropic.Anthropic | None = None, api_key: str | None = None, max_retries: int = 2, timeout: float = 120.0)`, with `name = "anthropic"`.
  - The client is created lazily on the first `generate`. The key comes from `api_key` or `os.environ["ANTHROPIC_API_KEY"]`. If neither is set, it raises `LLMConfigError("ANTHROPIC_API_KEY is not set")`.
  - `generate` calls `client.messages.parse(model=..., max_tokens=..., system=..., messages=[{"role": "user", "content": prompt}], output_format=request.schema)`.
  - Error mapping: `pydantic.ValidationError` → `LLMOutputError`; `anthropic.APIError` → `LLMProviderError` (`raise ... from exc`, message = exception class name plus status, never the key); `stop_reason == "refusal"` or `parsed_output is None` → `LLMOutputError`.
  - `close()` closes only a client the provider created itself. The provider also supports `with` (`__enter__`/`__exit__`).
  - `__repr__` shows the model only.
- `__init__.py`: re-exports the public names, `build_provider`, and `PROVIDERS`, the registry `{"anthropic": ..., "fake": ...}`. `build_provider(settings: LLMSettings) -> LLMProvider` is the only place that branches on the provider name. `fake` gets an empty-response `FakeProvider` (callers or tests that need canned output construct `FakeProvider` directly).

Changes to `config.py`, additive only:

- `GenerationMode(StrEnum)`: `PRECOMPUTED = "precomputed"`, `LIVE = "live"`.
- `generation_mode() -> GenerationMode`.
- `LLMSettings`, a frozen dataclass with `provider` and `model`.
- `llm_settings() -> LLMSettings`. The default provider is `anthropic`. The default model per provider is `anthropic` → `claude-sonnet-5-5` and `fake` → `fake-model`, in a `DEFAULT_MODELS` dict.
- Unknown values raise `ConfigError(ValueError)`, which is defined in `config.py`. `llm.base.LLMConfigError` subclasses both `LLMError` and `ConfigError`. `config` must not import `llm`.
- The API key is not read in `config.py`.

Dependency direction: `config` → `llm`. Nothing else imports `llm` yet. Only `ideology_app.llm.anthropic_provider` may import `anthropic`.

Tests:

- `tests/test_llm.py` covers config, registry and fake. `tests/test_llm_anthropic.py` covers the adapter through `httpx2.MockTransport`; build each mock client with `with httpx2.Client(...)` so it is closed.
- Each file has an autouse fixture that deletes the four env vars and blocks socket connects (Scenario 9). Keep this in the test modules, not `tests/conftest.py`, to avoid merge conflicts with the parallel branch.

## Expected File Changes

- `pyproject.toml`: modify. Add `"anthropic>=1.15,<2"` and `"pydantic>=2"` to `dependencies`. This is the only change; it may conflict trivially with a parallel branch, so resolve by keeping both.
- `src/ideology_app/config.py`: modify, additive. Add `GenerationMode`, `generation_mode`, `LLMSettings`, `llm_settings`, `DEFAULT_MODELS` and the config error.
- `src/ideology_app/llm/__init__.py`, `base.py`, `fake.py`, `anthropic_provider.py`: create.
- `tests/test_llm.py`, `tests/test_llm_anthropic.py`: create.
- `ARCHITECTURE.md`, `CONSTRAINTS.md`: modify (see below).
- `feature_list.json`, `PROGRESS.md`: status and evidence only.

## Visual Design Impact

- UI involved: no. Design source: not applicable. No browser validation needed (no browser-visible change).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update. Add an "LLM Providers" section covering the package layout, the `LLMProvider` protocol, `build_provider`/registry, the env vars and defaults, the `config` → `llm` direction, and "add a provider = new module + one registry entry + one `DEFAULT_MODELS` entry".
- `CONSTRAINTS.md`: update. Add these rules:
  - Only `ideology_app.llm.*_provider` modules may import a vendor SDK. Everything else gets a provider through `build_provider` or by injection. Reason: provider is configuration, not code branches.
  - Tests MUST NOT need or read a real API key or open a network connection. Use `FakeProvider`, or inject a client backed by `httpx2.MockTransport`. Reason: the AGENTS.md invariant and a deterministic CI.
  - API keys MUST NOT appear in reprs, error messages or logs.
- `AGENTS.md`: not needed. Its invariants already cover this.
- `docs/technical-discovery.md`: not needed. The config table already names `LLM_PROVIDER`/model and `GENERATION_MODE`.

## Implementation Plan

1. Add the dependencies and run `.venv/bin/pip install -e '.[dev]'`.
2. Add the config settings and errors, with tests (Scenarios 2–3).
3. Add `llm/base.py` and `llm/fake.py`, with tests (Scenarios 4–5).
4. Add `llm/anthropic_provider.py`, with MockTransport tests (Scenarios 6–8).
5. Add the registry and `build_provider`, with tests (Scenario 1).
6. Add the offline guard to both test modules, then run the gate (Scenario 9).
7. Update the docs, `feature_list.json` (status `passing` plus evidence) and `PROGRESS.md`.

## Implementation Tasks

- [ ] `pyproject.toml`: add `anthropic`, `pydantic`.
- [ ] `config.py`: `GenerationMode`, `generation_mode()`, `LLMSettings`, `llm_settings()`, defaults, config error.
- [ ] `llm/base.py`: request, result, protocol, error hierarchy.
- [ ] `llm/fake.py`: `FakeProvider` (dict / instance / callable responses, `calls`, deterministic tokens).
- [ ] `llm/anthropic_provider.py`: lazy client and key, `messages.parse`, error mapping, `close`/context manager, safe `__repr__`.
- [ ] `llm/__init__.py`: `PROVIDERS`, `build_provider`, re-exports.
- [ ] `tests/test_llm.py`, `tests/test_llm_anthropic.py`, each with the autouse offline and env guard.
- [ ] `ARCHITECTURE.md`, `CONSTRAINTS.md`.

## Verification Plan

- `CI=true ./init.sh`: exit 0. pytest reports 49 + N passed, with no warnings.
- `.venv/bin/python -X dev -W error -m pytest -p no:cacheprovider tests/test_llm.py tests/test_llm_anthropic.py`: clean.
- `env -u ANTHROPIC_API_KEY .venv/bin/python -m pytest -q tests/test_llm*.py`: passes, so no key is needed.
- `grep -rn "import anthropic\|from anthropic" src tests` shows only `src/ideology_app/llm/anthropic_provider.py` and `tests/test_llm_anthropic.py`.
- `.venv/bin/python -c "from ideology_app.llm import build_provider; from ideology_app.config import llm_settings; print(build_provider(llm_settings()))"` with no key set prints an `AnthropicProvider` repr and does not error.
- No E2E harness exists, and this feature has no user or API flow, so unit tests with a mocked transport are enough.
- `init.sh` needs no change. It keeps running the install step and pytest only and starts no server.

## Evidence To Capture

- `init.sh` exit code and pytest count; the `-X dev -W error` run; the result of the no-key run; the grep output; the names of the tests that cover Scenarios 1–9. Record this in `feature_list.json` → `llm-provider-abstraction.evidence` and in a `PROGRESS.md` session entry. Do not create `docs/validations/`.

## Validator Checklist

- [ ] Scenarios 1–9 are each covered by a named test, and the tests pass.
- [ ] No test needs `ANTHROPIC_API_KEY` or opens a socket. The guard is present in both LLM test modules.
- [ ] Provider selection happens only in `build_provider`/`PROVIDERS`. No `if provider == ...` appears elsewhere.
- [ ] The key is read only lazily, inside `AnthropicProvider`, and never appears in a repr or error.
- [ ] No pipeline, prompt, schema-for-Statements, migration, CLI or UI work was added. `cli.py`, `main.py` and `tests/conftest.py` are unchanged.
- [ ] `ARCHITECTURE.md` and `CONSTRAINTS.md` are updated. `feature_list.json` and `PROGRESS.md` are updated with evidence.

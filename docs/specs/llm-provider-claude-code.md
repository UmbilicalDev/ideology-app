# Feature Implementation Spec: LLM provider that uses the local Claude Code CLI

## Source Feature

- `id`: llm-provider-claude-code
- `area`: llm
- `depends_on`: none (`llm-provider-abstraction` is already accepted)
- `status`: not_started (at planning time)
- `source`: `feature_list.json`. `e2e-real-2023-election` depends on this feature.

## Goal

Add a third provider, `claude_code`, to the existing registry. With `LLM_PROVIDER=claude_code`, every pipeline LLM call runs the Operator's local Claude Code CLI (`claude -p`) with structured JSON output and no tools, using the Operator's own Claude subscription. No API key is needed or read. When the CLI reports the subscription usage limit, the provider waits in-process until the reported reset, then retries the same request. A multi-hour run (about 176 calls, about 2.1M input tokens for the 2023 election) can then finish across several usage-limit windows instead of failing.

The provider is for local Operator use only, never for a production deployment (use `anthropic` there). Pipeline code, chunking, prompts and schemas stay exactly as they are.

## Non-Goals

- No change to `pipeline/` (prompts, chunking, call caps, schemas), `runs.py`, `cli.py`, migrations or UI. The user explicitly rejected re-chunking or reading manifestos fewer times.
- No checkpoint/resume. If the process dies, the run is lost; Ctrl-C keeps ending it `failed: interrupted`.
- No real `claude` call in tests or by the implementer. Running `e2e-real-2023-election` belongs to that feature.
- No price/cost table, no `--max-budget-usd`, and no `--bare` (it forces API-key auth).
- No new dependency (stdlib `subprocess`, `json`, `tempfile`, `shutil`, `zoneinfo` only).

## Job Story

When I run the real pipeline on my laptop without paying for API usage,
I want each LLM call to go through my logged-in Claude Code CLI and wait out usage limits by itself,
so I can start one long run, keep the machine awake, and get a finished Pipeline Run.

## Users And Permissions

- Operator: sets `LLM_PROVIDER=claude_code` (and optionally `LLM_MODEL` and the `LLM_CLAUDE_CODE_*` variables below) and must be logged in to Claude Code with a Claude subscription (`claude auth login`). Uses it only locally.
- Voters: not involved. Nothing changes in the API or web client.

## Acceptance Scenarios

1. **Registry.** Given `LLM_PROVIDER=claude_code` and no `LLM_MODEL`, `llm_settings()` returns `("claude_code", "claude-sonnet-4-6")`. `build_provider` returns a `ClaudeCodeProvider` with `name == "claude_code"`, so `PipelineRun.llm_provider/llm_model` record `claude_code` / `claude-sonnet-4-6`. `set(PROVIDERS) == set(DEFAULT_MODELS) == {"anthropic", "claude_code", "fake"}`, and an invalid `LLM_PROVIDER` lists `anthropic, claude_code, fake`.
2. **Invocation.** Given a fake runner that returns a success envelope, `generate(request)` calls the runner once with the exact argv below, `input=request.prompt`, a temporary empty `cwd`, the sanitised env, and the configured timeout. It returns `LLMResult(output=<validated schema instance>, provider="claude_code", model=<model>, input_tokens=<sum>, output_tokens=<n>)`.
3. **Schema mismatch.** Given a success envelope whose `structured_output` does not validate against `request.schema` (or is missing), `generate` raises `LLMOutputError` naming the task and schema. The same happens for subtype `error_max_structured_output_retries` and assistant error `max_output_tokens`.
4. **Usage limit, then success.** Given a fake runner whose first envelope is a usage-limit error resetting at T, and a fake clock at T−2h, the provider logs one stderr line with the local resume time, sleeps (fake) until T + 2 min, and calls the runner again with the identical argv and stdin. It returns the second result. Variants: the reset comes from `rate_limit_event.resetsAt`; the reset is parsed from the text (`"… · resets 3pm (Europe/Madrid)"`, `"… · resets Oct 23, 3:30pm (Europe/Madrid)"`); the reset is missing or unparsable, so the provider waits `USAGE_LIMIT_FALLBACK_WAIT` (30 min) and probes again.
5. **Wait budget.** Given `LLM_CLAUDE_CODE_MAX_WAIT_HOURS=1` and a reset 3h away (or cumulative waits over 1h), `generate` raises `LLMProviderError` saying the usage limit resets at <time> beyond the configured maximum wait. It does not sleep first.
6. **Transient errors.** Given envelopes with `api_error_status` 429 that are not a usage limit (e.g. `"API Error: Server is temporarily limiting requests (not your usage limit) · …"`), 500/502/503/504/529, assistant error `server_error`, or `subprocess.TimeoutExpired`, the provider retries up to `TRANSIENT_RETRIES = 3` times with backoff 30 s / 120 s / 300 s, logging one line each, then raises `LLMProviderError`. A success on a retry returns normally.
7. **Other errors.** An auth failure (`api_error_status` 401/403 or assistant error `authentication_failed`) raises `LLMConfigError` ("Claude Code is not logged in or its login expired; run `claude auth login`"), with no retry. Non-JSON stdout, an envelope with no `result` element, `error_during_execution` / `error_max_turns` / `error_max_budget_usd`, `invalid_request`, `billing_error` or anything unknown raises `LLMProviderError` with no retry. Messages include the task, subtype, `api_error_status`, the exit code and at most 200 characters of the CLI's `result` text. They never include the prompt, the env or raw stderr beyond 200 characters.
8. **CLI missing or not logged in, before any DB write.** Given `LLM_PROVIDER=claude_code` and `claude` not found (`shutil.which` returns `None`), `ideology pipeline run --election 1` exits 1 with `Error: Claude Code CLI 'claude' not found on PATH; install it or set LLM_CLAUDE_CODE_BIN`, and no Pipeline Run row exists. The same applies when the preflight `claude auth status --json` exits non-zero, says `loggedIn: false`, or reports an `authMethod` other than `claude.ai` / `oauth_token` (an API key would bill the API). Invalid `LLM_CLAUDE_CODE_*` values behave the same way (`ConfigError`).
9. **Offline.** No test starts the real CLI or opens a socket. The new test module's autouse guard replaces the provider module's seams `run_cli` and `find_cli` with failing stubs, unsets `ANTHROPIC_API_KEY`, `LLM_*` and `LLM_CLAUDE_CODE_*`, and blocks sockets. `CI=true ./init.sh` passes.

## Repository Research

### Files Inspected

- `src/ideology_app/llm/{__init__,base,anthropic_provider,fake}.py`: the registry (`PROVIDERS`, `build_provider`), `LLMRequest`/`LLMResult`/`LLMProvider`, errors `LLMError` > `LLMConfigError` (also `config.ConfigError`), `LLMOutputError`, `LLMProviderError`; the Anthropic error mapping to mirror.
- `src/ideology_app/config.py`: `DEFAULT_MODELS`, `llm_settings()`, the `_env` and `_positive_int_env` helpers, the `ValidationSettings` pattern.
- `src/ideology_app/cli.py`: `_provider()` is called inside `except config.ConfigError` before `queue_run` (so a constructor `ConfigError` writes nothing); `close` is duck-typed.
- `src/ideology_app/pipeline/runs.py`: `_start` rejects a provider/model mismatch; `LLMError` → `failed: <message>`; `KeyboardInterrupt` → `failed: interrupted` and re-raise.
- `pipeline/prompts.py` (`max_tokens` 4096/8192; schemas use `maxItems`, `pattern`, `$defs`), `tests/test_llm.py`, `tests/test_cli_pipeline.py:190`, `tests/test_cli_live_mode.py:237,420` (they assert `supported values: anthropic, fake`).
- `ARCHITECTURE.md` (LLM Providers), `CONSTRAINTS.md` (LLM Providers), `docs/technical-discovery.md`, `docs/risks-and-open-questions.md`, `docs/specs/llm-provider-abstraction.md`, the three pipeline specs.
- Claude Code 2.1.110: `claude --help`, `claude auth status --help`, and the bundle `/usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js` (read for message strings and envelope schemas only; no credentials were read).

### Findings From The CLI (2.1.110)

- `--output-format json --verbose` prints a JSON array of every message (`system/init`, `assistant`, `user`, `rate_limit_event`, `result`). Without `--verbose` it prints only the `result` object. The exit code is 1 when `result.is_error`, else 0.
- The success `result` has `subtype: "success"`, `is_error: false`, `structured_output` (the schema-validated object), `usage` (`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`), `modelUsage` and `num_turns`. `--json-schema` is implemented as a `StructuredOutput` tool that the CLI validates and retries (`MAX_STRUCTURED_OUTPUT_RETRIES`, default 5). Then `subtype: "error_max_structured_output_retries"`.
- API errors produce `subtype: "success"`, `is_error: true`, `api_error_status: <HTTP>`, `result: <message>`, and an `assistant` message whose `error` is one of `authentication_failed | billing_error | rate_limit | invalid_request | server_error | unknown | max_output_tokens`.
- Subscription usage limit (HTTP 429 with `anthropic-ratelimit-unified-*` headers): the message is `"You've hit your <session limit|weekly limit|Sonnet limit|Opus limit|usage limit|limit>[ · resets <time>]"` or `"You're out of extra usage[ · resets <time>]"`. `<time>` is `3pm (Europe/Madrid)`, `3:30pm (…)`, or `Oct 23, 3pm (…)` (with `, 2027` when the year differs). The timezone is the CLI's IANA zone. A `rate_limit_event` with `rate_limit_info.status: "rejected"`, `resetsAt` (epoch seconds) and `rateLimitType` is emitted when limit info changes. Whether it is present on every limit error is unverified, so it is preferred but not required. A non-usage 429 says `"Server is temporarily limiting requests (not your usage limit)"`, so match on the message prefix, never on the substring "usage limit".
- `CLAUDE_CODE_DISABLE_CLAUDE_MDS`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY`, `CLAUDE_CODE_DISABLE_ATTACHMENTS` (stops `@path` mentions in manifesto text from attaching files), `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, `CLAUDE_CODE_DISABLE_THINKING` and `CLAUDE_CODE_MAX_OUTPUT_TOKENS` exist. `--setting-sources ""` loads no user/project/local settings (hooks, env, `apiKeyHelper`); managed policy settings still apply. `--system-prompt-file` exists but is hidden, so use `--system-prompt`.
- `claude auth status --json` exits 0/1 and prints `{loggedIn, authMethod, apiProvider, …}` (plus email/org for `claude.ai`; the provider must read only `loggedIn` and `authMethod`).
- **The one real call** (cwd = empty temp dir, this spec's flags with `--model sonnet`, stdin "Reply OK…") returned exit 1 in 1.9 s with a 3-element array. `init` showed `model: "claude-sonnet-4-6"`, `tools: ["StructuredOutput"]` (so `--tools ""` keeps only structured output), `mcp_servers: []`, `apiKeySource: "none"`, and `cwd` = the temp dir. The `assistant` message had `error: "authentication_failed"`. The `result` had `subtype: "success"`, `is_error: true`, `api_error_status: 401`, `result: "Failed to authenticate. API Error: 401 … OAuth access token has expired …"`, and an all-zero `usage`. The cause was the agent harness's injected session auth, which was inherited through `CLAUDE_CODE_*` env vars. That is why the env rule below strips them. A successful `structured_output` envelope was **not** observed live.

## Technical Approach

**Config** (`config.py`): add `DEFAULT_MODELS["claude_code"] = "claude-sonnet-4-6"`. This is the full id that the CLI's `sonnet` alias resolves to in 2.1.110. A pinned id makes `llm_model` exact; `LLM_MODEL=sonnet` stays possible. Add a frozen `ClaudeCodeSettings(bin: str, timeout_seconds: int, max_wait_hours: int)` and `claude_code_settings()`, which read `LLM_CLAUDE_CODE_BIN` (default `claude`), `LLM_CLAUDE_CODE_TIMEOUT_SECONDS` (default 900, via `_positive_int_env`) and `LLM_CLAUDE_CODE_MAX_WAIT_HOURS` (default 48). An invalid value raises `ConfigError`.

**Provider** (`llm/claude_code_provider.py`, `ClaudeCodeProvider`, `name = "claude_code"`):

- Signature: `__init__(model, *, settings=None, runner=None, which=None, clock=None, sleep=time.sleep, log=None)`; `which=None` → module-level seam `find_cli` (= `shutil.which`), resolved at call time so tests can monkeypatch it. `settings=None` means `config.claude_code_settings()`. `runner=None` means the module-level `run_cli(argv, *, input, env, cwd, timeout) -> subprocess.CompletedProcess[str]`, which wraps `subprocess.run(..., capture_output=True, text=True, encoding="utf-8", check=False)`. Tests monkeypatch this seam. `clock` returns an aware UTC `datetime` (default `datetime.now(UTC)`). `log` writes one line to `sys.stderr`, flushed.
- Constructor preflight: resolve `which(settings.bin)`. If missing, raise `LLMConfigError`. Then run `[bin, "auth", "status", "--json"]` (timeout 30 s, sanitised env, temp cwd). If the exit code is non-zero, the JSON is unparsable, `loggedIn` is not true, or `authMethod` is not `claude.ai`/`oauth_token`, raise `LLMConfigError`. Update the `build_provider` docstring ("no client or key is touched yet" → this preflight). `__repr__` → `ClaudeCodeProvider(model=…)`. `close()` is a no-op.
- argv (fixed order): `[bin, "-p", "--output-format", "json", "--verbose", "--model", model, "--system-prompt", request.system, "--json-schema", json.dumps(request.schema.model_json_schema()), "--tools", "", "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands"]`. The prompt goes on stdin.
- Isolation: every call runs in a fresh `tempfile.TemporaryDirectory(prefix="ideology-claude-")` used as a context manager (no `ResourceWarning`), so no project `CLAUDE.md`/`AGENTS.md`/`.claude/`/`.mcp.json` is discovered. `--setting-sources ""` drops hooks and settings, and `--strict-mcp-config` drops MCP servers.
- Child env: a copy of `os.environ` minus every name starting with `ANTHROPIC_` or `CLAUDE` (covers `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `CLAUDECODE`, `CLAUDE_CODE_USE_BEDROCK/VERTEX/FOUNDRY`, `CLAUDE_CODE_SIMPLE` and inherited session vars), except `CLAUDE_CODE_OAUTH_TOKEN` (subscription token from `claude setup-token`) and `CLAUDE_CONFIG_DIR`. Then set `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, `CLAUDE_CODE_DISABLE_ATTACHMENTS=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `CLAUDE_CODE_DISABLE_THINKING=1` (parity with the Anthropic adapter, which uses no thinking, and it saves usage), and `CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(request.max_tokens)`. The provider never reads, logs or passes a key.
- Parsing: run `json.loads(stdout)`. A list means the `result` element is the last one with `type == "result"`, plus all `rate_limit_event` and `assistant.error` values. A dict is the result itself. Success (`subtype == "success"` and not `is_error`) means `request.schema.model_validate(result["structured_output"])`; a `ValidationError` or missing value raises `LLMOutputError`. Tokens: `input_tokens = input_tokens + cache_creation_input_tokens + cache_read_input_tokens` and `output_tokens = output_tokens` (missing or non-int → 0). These are summed by the CLI over its internal turns. Failed attempts' usage is not counted.
- Classification order: usage limit, then auth, then transient, then output, then other (Scenarios 3–7). Usage limit means a `rate_limit_event` with status `rejected`, or a `result` that starts with `"You've hit your"` or `"You're out of extra usage"`. Reset time: first `resetsAt` (epoch s), else the text after `" · resets "`, parsed with `zoneinfo` for formats `h[:mm]am|pm (Zone)` (today in that zone, tomorrow if already past) and `Mon D[, YYYY], h[:mm]am|pm (Zone)`, else the fallback.
- Waiting: target = reset + `USAGE_LIMIT_MARGIN` (2 min), with at least 60 s. If cumulative waits would exceed `max_wait_hours`, raise `LLMProviderError`. Otherwise log `claude_code: usage limit reached (task <task>); waiting until <local ISO time> before retrying (Ctrl-C to stop)`. Sleep in slices of at most 60 s until `clock() >= target`, so laptop sleep does not shift the target. Then retry the identical call. `KeyboardInterrupt` from sleep or `subprocess.run` propagates unchanged (`subprocess.run` kills the child), so `runs.py` records `interrupted`.

**Registry** (`llm/__init__.py`): `"claude_code": lambda model: ClaudeCodeProvider(model)`, plus re-export. No branch on the provider name anywhere else.

## Expected File Changes

- `src/ideology_app/config.py`: modify (default model, `ClaudeCodeSettings`, `claude_code_settings()`).
- `src/ideology_app/llm/claude_code_provider.py`: create.
- `src/ideology_app/llm/__init__.py`: modify (registry entry, export, docstring).
- `tests/test_llm_claude_code.py`: create (Scenarios 2–9, fake runner/clock/sleep/log, envelope builders matching the shapes above).
- `tests/test_llm.py`, `tests/test_config.py`: modify (registry set, `claude_code` settings, env var validation).
- `tests/test_cli_pipeline.py`, `tests/test_cli_live_mode.py`: modify the `supported values` strings, and add the Scenario 8 CLI test (`LLM_PROVIDER=claude_code`, `LLM_CLAUDE_CODE_BIN=/nonexistent/claude`; assert exit 1, the message naming that bin, zero `PipelineRun` rows).

## Visual Design Impact

- UI involved: no. Browser validation does not apply because there is no browser-visible change (AGENTS.md exemption for CLI/pipeline features).

## Durable Documentation Impact

- `ARCHITECTURE.md`: update the LLM Providers section (the provider, argv/env/isolation, usage-limit handling, `LLM_CLAUDE_CODE_*` config, tests, `DEFAULT_MODELS`), the `LLM_PROVIDER` values, and the header feature list.
- `CONSTRAINTS.md`: update. Only `llm/claude_code_provider.py` MAY spawn the `claude` CLI. Tests MUST NOT spawn it (inject `runner`, keep the autouse guard). The child env MUST strip `ANTHROPIC_*`/`CLAUDE*` (except the two allowed names), and `--bare` MUST NOT be used. `claude_code` MUST NOT be used in a deployment or to serve Voters.
- `docs/technical-discovery.md`: update the Configuration Points row (`anthropic`, `claude_code` (local Operator only), `fake`) and add an Integrations entry with the runbook: `claude auth login` once, then `caffeinate -is env LLM_PROVIDER=claude_code .venv/bin/ideology pipeline run --election N`. Keep the process and the machine awake (on AC power, lid open). There is no resume. Ctrl-C ends the run `failed: interrupted`.
- `docs/risks-and-open-questions.md`: update "Provider cost/availability" (no API spend with `claude_code`, but usage-limit bound and multi-hour). Update "Real-LLM behaviour unverified" (add `claude-sonnet-4-6`; the live success envelope was not yet observed; the CLI validates the schema itself and retries up to 5 times, each retry re-sending the chunk). Update "Queued run pinned…" (switching `anthropic` ↔ `claude_code` is a provider change). Add: "Usage limits and multi-hour runs (`e2e-real-2023-election`)" (no checkpoint, sleep/kill loses the run, a weekly reset beyond `LLM_CLAUDE_CODE_MAX_WAIT_HOURS` fails the run, structured output takes at least 2 model turns per call); "Claude Code CLI output format may change" (detection relies on 2.1.110 strings and fields; unknown shapes fail closed as `LLMProviderError`/`LLMOutputError`); and an open question on "Subscription terms for automated local use" (the Operator confirms it fits Anthropic's consumer terms; local and personal only).
- `AGENTS.md`: not needed (invariants unchanged; tests still use only fakes). `CONTEXT.md`: not needed.

## Implementation Plan

1. Config: default model, settings dataclass and reader, with tests.
2. Provider: env and argv builders, preflight, parse/classify, wait/retry loop, with tests driven by a fake runner, clock and sleep.
3. Registry entry and exports. Fix the `supported values` test strings. Add the CLI Scenario 8 test.
4. Docs and risks updates. Run `CI=true ./init.sh`. Record evidence in `feature_list.json` and `PROGRESS.md`.

## Implementation Tasks

- [ ] `config.py`: `DEFAULT_MODELS["claude_code"]`, `ClaudeCodeSettings`, `claude_code_settings()`.
- [ ] `claude_code_provider.py`: `run_cli` seam, `_child_env`, `_argv`, preflight, `_parse_envelope`, `_classify`, `_parse_reset`, wait loop, constants `TRANSIENT_RETRIES`, `TRANSIENT_BACKOFF`, `USAGE_LIMIT_MARGIN`, `USAGE_LIMIT_FALLBACK_WAIT`.
- [ ] `llm/__init__.py`: registry entry, export, docstring.
- [ ] Tests: `test_llm_claude_code.py` with one named test per scenario and variant, plus edits to `test_llm.py`, `test_config.py`, `test_cli_pipeline.py` and `test_cli_live_mode.py`.
- [ ] Docs: `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/technical-discovery.md`, `docs/risks-and-open-questions.md`.

## Verification Plan

- `CI=true ./init.sh`: exit 0 (pytest with `filterwarnings=error`, then the web steps unchanged).
- `env -u ANTHROPIC_API_KEY PATH=/usr/bin:/bin .venv/bin/python -m pytest -q tests/test_llm*.py tests/test_config.py tests/test_cli_pipeline.py tests/test_cli_live_mode.py`: passes with `claude` off `PATH`, which proves no test needs the real CLI.
- `grep -rn "subprocess" src/ideology_app/llm` lists only `claude_code_provider.py`. `grep -rn "claude_code" src --include=*.py` shows no branch outside `llm/` and `config.DEFAULT_MODELS`.
- The implementer makes no real `claude` call. The first live call happens in `e2e-real-2023-election`, which should start with one small manual smoke run.
- No E2E harness applies (CLI/provider only).

## Evidence To Capture

- The gate exit code and pytest count; the restricted-`PATH` run; the grep output; test names per scenario. Record them in `feature_list.json` → `llm-provider-claude-code.evidence` and in a `PROGRESS.md` session entry. Do not create `docs/validations/`.

## Validator Checklist

- [ ] Scenarios 1–9 each have a passing named test; no test spawns `claude` or opens a socket.
- [ ] argv contains no `--bare`, includes `--tools ""` and `--no-session-persistence`, and uses a temp cwd. The env strips `ANTHROPIC_*`/`CLAUDE*` and never reads a key.
- [ ] Usage-limit detection uses the prefixes/`rate_limit_event`, not the substring "usage limit"; the "not your usage limit" 429 is transient.
- [ ] Waits are bounded by `LLM_CLAUDE_CODE_MAX_WAIT_HOURS`; Ctrl-C still yields `failed: interrupted`.
- [ ] `pipeline/` (prompts, chunking, caps), `runs.py`, `cli.py` and migrations are unchanged.
- [ ] Docs and risks are updated as listed; `feature_list.json` and `PROGRESS.md` have evidence.

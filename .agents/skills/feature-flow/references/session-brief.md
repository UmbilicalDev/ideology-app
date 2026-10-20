# Feature-Flow Session Brief

Use this template when one session (an orchestrator, for example `$github-flow` in `run` mode) starts another session to run `$feature-flow` for one feature. The new session starts with no conversation history, so the brief must carry everything it can't find in the repo.

The orchestrator owns git publishing: pushing, PRs, merging and updating the user's local base branch. The feature-flow session owns planning, implementation, validation, and the local acceptance commit.

## Before Writing The Brief

Gather these facts; don't guess them:

1. The feature entry in `feature_list.json`: `title`, `user_visible_behavior`, `depends_on`, `verification`, `notes`.
2. That every `depends_on` feature is `accepted` on the base branch.
3. The base SHA, the branch and the worktree path. With `$github-flow`, the branch and worktree come from its `config.json`.
4. The issue number, if issues are used.
5. The entries in `docs/risks-and-open-questions.md` that name the feature (`grep -n "<feature-id>"`).
6. Whether the feature changes anything a user sees in a browser. If it does, AGENTS.md "Browser Validation For UI Features" applies.
7. Which features run in parallel on other branches, and the current Alembic head, so a new migration id can be renumbered on merge.

## Prompt Template

````md
Use $feature-flow to complete feature `<feature-id>` in this folder, until it is accepted. Read and follow `.agents/skills/feature-flow/SKILL.md`.

- **Location:** this folder is a git worktree on branch `<branch>`, cut from `<base-branch>` @ <base-sha>. First confirm with `git rev-parse --short HEAD` and `git branch --show-current`; if either differs, stop and report. Stay on this branch.
- **Tracking:** the feature is issue #<n> (<issue-url>). Put "Closes #<n>" in the acceptance commit message body.
- **Roles:** use the project subagents `planner`, `implementer` and `validator` (`.claude/agents/`), in this order: planner writes `docs/specs/<feature-id>.md`, then implementer, then validator. A `revise` verdict goes back to the implementer and then to the validator again.
- **Acceptance:** on accept, set the status to `accepted` with the validator's evidence in `feature_list.json` and `PROGRESS.md`, then create one Conventional Commit `feat: complete <feature-id>` on this branch.

**Behaviour** (feature_list entry): <user_visible_behavior, verification and notes, restated precisely>.

**Design points the spec must settle:** <open choices this feature forces, e.g. state transitions, contracts with other features, defaults, edge cases. Name what is out of scope and which later feature owns it>.

**Reuse:** <existing modules, registries or patterns the feature must plug into (see ARCHITECTURE.md), and "don't redesign X">.

**Risks doc entries naming this feature** (settle each or explicitly defer it, and update `docs/risks-and-open-questions.md`):
- <entry 1>
- <entry 2>

**Browser validation** (UI features only): mandatory. Load the served build in a real browser at 375px and desktop width, walk through every acceptance scenario, check the console and network, and record the browser and widths in the evidence. If no browser tool is usable, stop and report it; don't mark the feature `passing`. For a feature without UI, say: "Browser validation doesn't apply; record that."

User constraints:
- No push and no PR; the orchestrating session publishes and merges.
- Never create `docs/validations/`. Evidence goes only in `feature_list.json` and `PROGRESS.md`.
- Follow "Risks And Open Questions" in AGENTS.md.
- Tests never call a real LLM (use `FakeProvider`), need no real API key, and use no network.
- Touch only this feature's scope.
- If a dependency, permission or environment is missing, stop and report it rather than working around it.

Done looks like: the feature accepted and committed locally. Final report fields: session, branch, status, commit hash, a one-line evidence summary (including the browser check for UI features), and "PR: none (main session publishes)".
````

When the session starts without this conversation's history, also pass a short background (at least 80 characters). It should cover:
- the stack and the current gate (`CI=true ./init.sh` and its steps);
- the accepted features this one builds on;
- the docs to read first (AGENTS.md, ARCHITECTURE.md, CONSTRAINTS.md, CONTEXT.md, DESIGN.md for UI, docs/domain-model.md, docs/risks-and-open-questions.md, and the specs of the features it builds on);
- any sibling features running in parallel, and the next free migration id.

## After The Session Reports

Treat the report as a claim. Before publishing, the orchestrator checks:

- the branch has exactly one new commit, `feat: complete <feature-id>`, and its merge base is the expected base SHA;
- the feature is `accepted` in `feature_list.json` on the branch, with validator evidence;
- there is no `docs/validations/` and the worktree is clean;
- `docs/risks-and-open-questions.md` reflects what the feature settled or added;
- new migrations and dependency changes are expected (`git diff --name-only <base> <branch> -- <migrations dir> <manifests>`);
- `CI=true ./init.sh` passes, either in the worktree or after the merge on the base branch.

When features ran in parallel, merge them one at a time. Merge the base branch into each later branch, then resolve `PROGRESS.md` by keeping both sides' entries and renumbering the later branch's sessions after the base branch's. Re-run the gate before pushing the merge.

---
name: github-flow
description: Coordinate GitHub Flow work around feature-flow on any git host
  (GitHub, GitLab, others): issues, branches, worktrees, parallel runs and
  PRs/MRs. Works with gh, glab or plain git. Use when asked to plan, run or
  publish one or more features from feature_list.json.
---
## Modes
- plan: read-only. Never mutates git, the forge or files.
- run: one issue + branch + worktree + session per feature, same base SHA.
- publish: push and open PRs/MRs only for accepted features. Never merge.
## Configuration
Read `config.json` (next to this file) first; commands are in
`references/forges.md`.
- `forge`: `auto` (from the remote host) | `github` | `gitlab` | `other`.
- `remote`, `base_branch`, `branch_prefix`: branch is `<prefix><feature-id>`.
- `worktree_root`: worktrees go in `<worktree_root>/<feature-id>`;
  `{repo}` is the repository folder name.
- `issues`: `auto` | `cli` | `link` | `off`.
- `change_requests`: `auto` | `cli` | `push-options` (GitLab only) | `link`.
- `compare_url` (optional, `other` forge): new PR/MR URL with `{base}` and
  `{branch}`.

`auto` resolves to `cli` when the forge CLI (`gh` for GitHub, `glab` for
GitLab) runs and is authenticated. Otherwise issues resolve to `link`, and
change requests to `push-options` on GitLab or `link` elsewhere. Branches,
worktrees, base SHA and pushes always use plain git.
## Hard Rules
- Reuse existing issues, worktrees and PRs/MRs. Never duplicate or delete work.
- One feature-flow session per worktree; never two features in one session.
- Detect tools and access by running the checks, never by assumption.
- A setting explicitly set to `cli` whose CLI is missing or unauthenticated
  is a missing dependency: stop and report it with the fix (install, or
  `gh auth login` / `glab auth login`). With `auto`, fall back and report it.
- Report anything a fallback cannot check as `unchecked`, never as checked.
- Stop and report if a permission, dependency or environment is missing.
- Never search for tokens or credentials to work around missing auth.
## Other Contributors
Other people push to this repository too (so far Miguel García and
`mostroh`), including merges into feature branches and PRs of their own.
- Before publishing or merging, check for open PRs/MRs by others and for new
  commits on the base branch (`git fetch`, `gh pr list --state open`). Report
  any that overlap the features at hand, for example a docs PR that changes
  the frontend stack before web features run.
- Before updating or pushing a feature branch, check for remote-only commits
  (`git log HEAD..<remote>/<branch>`). If someone already resolved a merge
  there, use their commit and verify it; never overwrite or force-push it.
- Never delete or rewrite someone else's branch or PR without the user's
  explicit approval.
## Parallel Branches
After one PR/MR of a parallel batch merges, bring each remaining branch up
to date by merging the base into it (never rebase a published branch), one
at a time, before its own PR/MR merges. Resolve conflicts with
`references/parallel-merges.md`. In particular, for `PROGRESS.md`, keep both
branches' sessions and renumber the later branch's sessions after the base
branch's.
## Practical Notes
Read `references/practical-notes.md` before running git or verification
commands. It covers checking a worktree's build in the browser through a
temporary `.claude/launch.json` entry, and the zsh and BSD `sed` pitfalls
already hit in this repository.
## Output
Once: forge, remote, base SHA, resolved issue and PR/MR modes, and why
(for example `gh unavailable: not on PATH`).
Per feature: session, issue, branch, status, commit, evidence, PR/MR URL.

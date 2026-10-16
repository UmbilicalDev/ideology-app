---
name: github-flow
description: Coordinate GitHub work around feature-flow: issues, branches,
  worktrees, parallel runs and PRs. Use when asked to plan, run or publish
  one or more features from feature_list.json.
---
## Modes
- plan: read-only. Never mutates git, GitHub or files.
- run: one issue + branch + worktree + session per feature, same base SHA.
- publish: push and open PRs only for accepted features. Never merge.
## Hard Rules
- Reuse existing issues, worktrees and PRs. Never duplicate or delete work.
- One feature-flow session per worktree; never two features in one session.
- Stop and report if a permission, dependency or environment is missing.
## Output
Per feature: session, branch, status, commit, evidence, PR URL.

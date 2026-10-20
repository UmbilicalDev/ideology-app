# Parallel Branches: Updating And Resolving Conflicts

Features run in parallel share a base SHA. Once one of their PRs/MRs merges, each remaining branch is behind the base branch and usually conflicts in the harness files every feature touches (`PROGRESS.md`, `feature_list.json`, `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md`), and sometimes in migrations.

Bring each remaining branch up to date before its own PR/MR merges, one branch at a time.

## Procedure

1. `git fetch <remote>`. Check the branch for commits that exist only on the remote (`git log --oneline HEAD..<remote>/<branch>`). If someone already merged the base into it, fast-forward to their commit and verify it instead of producing a competing resolution.
2. In the branch's worktree, run `git merge --no-ff --no-commit <remote>/<base>`. Merge, don't rebase: the branch is already published.
3. Resolve each conflict with the rules below. Keep both sides; never drop another feature's work.
4. Check that no conflict markers remain and that `feature_list.json` is valid JSON with acyclic `depends_on`.
5. Run the standard gate (`CI=true ./init.sh`) on the merged tree.
6. Commit with a message that says what was resolved and the gate result, push the branch, and confirm the PR/MR is mergeable again.

## Resolution Rules

### `PROGRESS.md`

- **Current Verified State:** combine both sides.
  - Keep the newest description of each command or path.
  - Recompute the next ready features from the merged `feature_list.json`.
  - Write "Last verified" only after the gate has passed on the merged tree.
- **Session log:** keep the base branch's sessions first, unchanged and in order. Then append the branch's sessions, renumbered to continue after the base branch's highest session number. A conflict at a shared `### Session N` header means both branches used number N, so give the branch's entry the next free number. Update any "Session N" references inside the moved entries.

### `feature_list.json`

Keep every feature's status and evidence from both sides. Two features never change the same entry, so a real conflict here means something is wrong: stop and report it.

### `ARCHITECTURE.md`, `CONSTRAINTS.md`, `docs/risks-and-open-questions.md`

- Keep both sides' entries.
- In lines that list features, such as "Current state after …", name all of them.
- If both sides edited the same risk entry, merge the texts into one entry. Don't keep two.

### Migrations

If both branches added the same revision id (e.g. two `0009` files), renumber the later branch's revision: its file name, its revision id, and `down_revision`, which must now point at the base branch's head. Then check there is a single head and that `alembic check` reports no drift.

### Code

Real code conflicts are rare when features are scoped well. If one needs a design decision rather than a mechanical merge, stop and report it to the user; don't decide it in the merge.

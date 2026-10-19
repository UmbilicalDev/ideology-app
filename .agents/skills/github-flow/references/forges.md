# Forge Adapters

Commands per forge and mode. `<remote>`, `<base>`, `<prefix>` come from
`config.json`; `<branch>` is `<prefix><feature-id>`; `<host>` and `<path>`
(`owner/repo`, or `group/subgroup/repo` on GitLab) come from
`git remote get-url <remote>` (`git@<host>:<path>.git` or
`https://<host>/<path>.git`). URL-encode titles in links.

## Detection

| Check | Command | Mutates |
|---|---|---|
| Forge (when `forge` is `auto`) | host `github.com` → `github`; host contains `gitlab` → `gitlab`; anything else → `other` | no |
| Remote access | `git ls-remote --exit-code <remote> HEAD` | no |
| Base SHA | `git ls-remote <remote> refs/heads/<base>` | no |
| Existing branch | `git ls-remote <remote> refs/heads/<branch>` and `git branch --list <branch>` | no |
| Existing worktree | `git worktree list --porcelain` | no |
| GitHub CLI | `gh --version` then `gh auth status` | no |
| GitLab CLI | `glab --version` then `glab auth status` | no |

A CLI counts as available only when both its commands exit 0. A binary that
exists but cannot run (for example quarantined by endpoint security) is
unavailable.

## Issues

| Mode | Find existing | Create |
|---|---|---|
| `cli` + github | `gh issue list --state all --search "<feature-id> in:title" --json number,title,state,url` | `gh issue create --title "<title>" --body "<body>"` |
| `cli` + gitlab | `glab issue list --all --search "<feature-id>" --output json` | `glab issue create --title "<title>" --description "<body>" --yes` |
| `link` + github | cannot check → report `unchecked` | report `https://<host>/<path>/issues/new?title=<title>` |
| `link` + gitlab | cannot check → report `unchecked` | report `https://<host>/<path>/-/issues/new?issue[title]=<title>` |
| `link` + other | cannot check → report `unchecked` | report `manual` |
| `off` | skip | skip |

In `link` mode the user creates the issue. Never report an issue number you
did not see.

## Change Requests (PR / MR)

Find existing first, in every mode:

| Forge | `cli` | Without CLI (match by commit SHA) |
|---|---|---|
| github | `gh pr list --state all --head <branch> --json number,state,url` | `git ls-remote <remote> 'refs/pull/*/head'` |
| gitlab | `glab mr list --all --source-branch <branch> --output json` | `git ls-remote <remote> 'refs/merge-requests/*/head'` |
| other | — | cannot check → report `unchecked` |

A SHA match against the pushed branch head means a PR/MR exists for that
commit; report it as `#<n> (matched by SHA)` and its URL
(`https://<host>/<path>/pull/<n>` or `https://<host>/<path>/-/merge_requests/<n>`).

Open one, only in `publish` and only when none exists:

| Mode | Command |
|---|---|
| `cli` + github | `git push -u <remote> <branch>` then `gh pr create --base <base> --head <branch> --title "<title>" --body "<body>"` |
| `cli` + gitlab | `git push -u <remote> <branch>` then `glab mr create --source-branch <branch> --target-branch <base> --title "<title>" --description "<body>" --yes` |
| `push-options` (gitlab only) | `git push -u <remote> <branch> -o merge_request.create -o merge_request.target=<base> -o "merge_request.title=<title>"`; GitLab prints the MR URL in the push output |
| `link` + github | `git push -u <remote> <branch>`, then report `https://<host>/<path>/compare/<base>...<branch>?expand=1` |
| `link` + gitlab | `git push -u <remote> <branch>`, then report `https://<host>/<path>/-/merge_requests/new?merge_request[source_branch]=<branch>&merge_request[target_branch]=<base>` |
| `link` + other | `git push -u <remote> <branch>`, then report `compare_url` from `config.json` with `{base}` and `{branch}` filled in, or `manual` when it is not set |

In `link` mode the PR/MR URL is `not opened` until the user opens it.

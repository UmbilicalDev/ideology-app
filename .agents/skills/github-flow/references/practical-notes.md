# Practical Notes

Things that went wrong or needed a workaround while orchestrating features in this repository. Read this before running git or verification commands from an orchestrating session.

## Checking A Worktree's Build In A Browser

UI features need a real-browser check (AGENTS.md "Browser Validation For UI Features"). The orchestrator re-checks before merging, and it must check the feature's worktree, not the main checkout.

In the Claude desktop app, the built-in browser starts servers from `.claude/launch.json`, which runs commands from the main checkout. To serve a worktree:

1. Run the gate in the worktree first (`CI=true ./init.sh`) so the web build exists.
2. Add a **temporary** entry to `.claude/launch.json`. Use `/usr/bin/env` to pass environment variables, use absolute paths into the worktree, and pick a free port:

   ```json
   {
     "name": "tmp-<feature-id>",
     "runtimeExecutable": "/usr/bin/env",
     "runtimeArgs": [
       "WEB_DIST_DIR=<worktree>/apps/web/dist",
       "DATABASE_URL=sqlite:///<scratch-dir>/check.db",
       "<worktree>/.venv/bin/uvicorn", "ideology_app.main:app", "--port", "8011"
     ],
     "port": 8011
   }
   ```

3. Build the scratch database outside the repo with the worktree's CLI (`<worktree>/.venv/bin/ideology db upgrade`, etc.). An unmigrated database makes the API answer 500. That's a known Low finding, not a regression.
4. Start it with `preview_start`. Check at 375px and at desktop width, read the console and network, then stop it with `preview_stop`.
5. **Remove the temporary entry** from `.claude/launch.json` and delete the scratch database. `git status` must be clean afterwards.

## Shell Pitfalls (zsh On macOS)

The shell is zsh, not bash. These all broke real commands:

- **`$var:...` is a zsh modifier.** `git show "$b:feature_list.json"` reads `:f` as a modifier and corrupts the argument. Write `"${b}:feature_list.json"`.
- **No word splitting of unquoted expansions.** `git push origin --delete $(cat list.txt)` passes the whole list as **one** argument, and nothing gets deleted. Loop over the items, or use an array.
- **`=word` expansion.** An argument like `===` or `== x` fails with "`== not found`". Quote it.
- **Globs that match nothing are errors** ("`no matches found`"). Quote the pattern, or check that the directory exists first.
- **`PIPESTATUS` is bash.** zsh uses lowercase `pipestatus`, indexed from 1.
- **`timeout` doesn't exist on macOS.** Rely on the tool's own timeout.
- **The working directory persists between commands, and `cd` into a worktree can be reset.** Use absolute paths, or `git -C <dir>`.

## Text Edits

- **macOS `sed` is BSD sed:** in-place editing needs `sed -i ''`. A replacement that contains `/`, backticks or other special characters easily breaks with "bad flag in substitute command". When a `sed` fails in the middle of an `&&` chain, nothing after it runs, so check what actually happened before carrying on.
- For multi-line edits, paths or Markdown replacements, use a short Python script (`str.replace`, then an `assert` that the placeholder is gone) instead of `sed`.
- After resolving conflicts, check that no conflict markers remain (`grep -nE '^(<<<<<<<|=======|>>>>>>>)'`) and that `feature_list.json` still parses.

## Verify, Don't Assume

When a command's output looks odd (a partial list, a count of 0, an error in the middle), list the real state before continuing: `git ls-remote --heads`, `git worktree list`, `gh pr view`. A failed batch command can look like a success.

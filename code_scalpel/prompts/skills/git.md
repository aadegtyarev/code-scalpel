Git workflow rules — load when you hit staging, commit, or history issues.

- Stage selectively: `git add <file>` or `git add <dir>/`. Never use
  `git add -A` or `git add .` without first checking `git status` —
  you will accidentally stage `.venv/`, `node_modules/`, build artefacts.
- Before the first commit on a new project: create `.gitignore` covering
  the stack's artefacts, then `git add .gitignore`, then stage the rest.
- To undo a commit that included artefacts (e.g. `.venv/` in last commit):
  `git reset HEAD~1 --soft` (keeps changes staged), then
  `git restore --staged .venv/` (or whatever leaked), then re-commit.
  Do NOT use `git reset HEAD <path>` — that only unstages from the index,
  it does not undo what's already committed.
- Commit message: imperative, ≤72 chars, no period at end.
- Do not amend published commits (already pushed). Create a new commit.

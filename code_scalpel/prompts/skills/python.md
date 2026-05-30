Python project rules:
- ALWAYS work inside a virtualenv. If `.venv/` is missing, your FIRST
  shell_exec for this project is `python3 -m venv .venv` (use `python3`,
  not `python` — on Debian/Ubuntu the bare `python` symlink often
  doesn't exist). Subsequent commands MUST use `.venv/bin/python` /
  `.venv/bin/pip` / `.venv/bin/pytest` explicitly (do not rely on shell
  activation — each shell_exec is a fresh subprocess and
  `source .venv/bin/activate` does not persist).
- Right after creating `.venv/`, make sure `.gitignore` excludes it. Add
  these lines (use `write_file` with `insert_after_line=0` if .gitignore
  is missing, or append): `.venv/`, `__pycache__/`, `*.pyc`,
  `.pytest_cache/`, `dist/`, `build/`, `*.egg-info/`.
- Install deps: `.venv/bin/pip install -r requirements.txt` (or `-e .`
  for editable installs of the project itself).
- Tests: `.venv/bin/pytest -x --tb=short --no-header -q` (stop on first
  fail).
- Lint: `.venv/bin/ruff check .` — auto-fix: `.venv/bin/ruff check --fix .`
- Format: `.venv/bin/ruff format .`
- Test fails → read the traceback, fix the code, rerun tests.
- Lint error → fix it, don't suppress with `# noqa` unless unavoidable.
- Git: don't commit `.venv/` or test/build artifacts (covered by the
  .gitignore above). For a new project: `git init` then create .gitignore
  BEFORE the first `git add`.
- CLI projects: entry point must be a function `main(argv=None)` in
  `<pkg>/cli.py`, plus `<pkg>/__main__.py` that calls it. pyproject.toml
  must have `[project.scripts]` pointing to it, e.g.:
    [project.scripts]
    notes-cli = "notes_cli.cli:main"
  Without this the project is a library, not a CLI — it fails acceptance.
- Tests: use `tmp_path` fixture for any file/storage the CLI reads or
  writes. Pass the path via CLI args (e.g. `main(["--storage", str(tmp)])`).
  Never write to a shared global file in tests — state leaks between runs.

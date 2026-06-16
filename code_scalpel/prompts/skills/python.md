Python project rules:
- First shell_exec: `python3 -m venv .venv` (use `python3`, not `python`).
  Always use `.venv/bin/python`/`.venv/bin/pip`/`.venv/bin/pytest` explicitly.
- Add to `.gitignore`: `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`,
  `dist/`, `build/`, `*.egg-info/`.
- For stdlib+pytest projects: skip `pip install -e .`. Create venv,
  `.venv/bin/pip install pytest`, add `pythonpath` to pyproject.toml:
    [tool.pytest.ini_options]
    pythonpath = ["."]
  Only use `pip install -e .` when there are third-party deps (fastapi, etc.).
- Tests: `.venv/bin/pytest -x --tb=short --no-header -q`.
- Lint: `.venv/bin/ruff check .` (fix: `ruff check --fix .`).
- Test fails → read traceback, fix, rerun.
- Lint error → fix, don't `# noqa` unless unavoidable.
- CLI projects: `main(argv=None)` in `<pkg>/cli.py`, `__main__.py` that calls it,
  `[project.scripts]` in pyproject.toml. Without this it's a library, not a CLI.
- Tests: use `tmp_path`, pass path via CLI args, never shared global state.

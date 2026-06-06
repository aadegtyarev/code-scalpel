"""Deterministic python-cli package resolution for run_smoke.

`python -m <pkg>` needs the importable package name. We resolve it from
the project itself — never a guess — in a fixed precedence so the same
project always yields the same `<pkg>`:

1. The hatchling wheel target declared in `pyproject.toml`
   (`[tool.hatch.build.targets.wheel] packages = ["src/<pkg>"]`) — the
   project's own declaration of what it ships.
2. A single `-m`-runnable package under `src/` (has `__main__.py`).
3. A single package directory under `src/`.

Ambiguity (multiple candidate packages) and absence both raise rather
than guess — a wrong `<pkg>` would make run_smoke fail confusingly.
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def resolve_pkg(root: Path) -> str:
    """Return the importable package name to run as `python -m <pkg>`."""
    declared = _from_pyproject(root)
    if declared is not None:
        return declared

    src = root / "src"
    if src.is_dir():
        pkg = _single_src_package(src)
        if pkg is not None:
            return pkg

    raise ValueError(
        f"cannot resolve a python-cli package under {root}: "
        "no hatchling wheel target and no single src/ package found"
    )


def _from_pyproject(root: Path) -> str | None:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return None
    packages = (
        data.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("packages")
    )
    if not isinstance(packages, list) or len(packages) != 1:
        return None
    entry = packages[0]
    if not isinstance(entry, str):
        return None
    # "src/<pkg>" → "<pkg>"; a bare "<pkg>" → "<pkg>".
    return Path(entry).name or None


def _single_src_package(src: Path) -> str | None:
    candidates = [
        child
        for child in sorted(src.iterdir())
        if child.is_dir() and (child / "__init__.py").is_file()
    ]
    if not candidates:
        return None
    runnable = [c for c in candidates if (c / "__main__.py").is_file()]
    if len(runnable) == 1:
        return runnable[0].name
    if len(candidates) == 1:
        return candidates[0].name
    return None

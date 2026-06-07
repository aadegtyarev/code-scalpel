"""Deterministic python-cli run-smoke resolution.

run-smoke needs both WHAT to run and HOW to invoke it. `resolve_pkg`
returns a typed `RunTarget(kind, target)` carrying both: the argv shape
(`module` → `python -m <target>`; `script` → `python <target>`) and the
target (the `-m` package/module name, or the script path). The descriptor
lets the adapter build the right argv without a second filesystem read.

Resolution is a fixed precedence ladder — never a guess — so the same
project always yields the same RunTarget. Declared (pyproject) shapes
outrank discovered (filesystem) shapes: an explicit project statement
always wins over a heuristic.

  1. hatchling wheel target declared in `pyproject.toml`
     (`[tool.hatch.build.targets.wheel] packages = [...]`) — the
     project's own ship declaration.                          → module
  2. single `[project.scripts]` console entry — also a declaration; the
     entry's `module:func` module is the `-m` target.         → module
  3. single package directory at the repo ROOT with `__main__.py`. → module
  4. single package under `src/` (runnable or sole package).  → module
  5. single root entry script from the config candidate list. → script

Ambiguity at any rung (e.g. two root scripts with no declared entry, two
hatchling targets, two `[project.scripts]` entries) raises rather than
guess — a wrong target/shape would make run-smoke fail confusingly or
false-demote a healthy deliverable. Absence of all rungs also raises
(today's contract).

Entry-points spec (declared outranks discovered):
https://packaging.python.org/en/latest/specifications/entry-points/
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_DEFAULT_SCRIPT_CANDIDATES = ("__main__.py", "main.py", "cli.py")

# Root-level directories that are never the deliverable package, even when a
# confused scaffold gives them `__init__.py` + `__main__.py`. `src` is the
# src-layout container (rung 4 inspects its children), `tests`/`docs` are
# scaffolding. Excluded from the root-package scan so `python -m src` can
# never be the resolved run target.
_RESERVED_ROOT_DIRS = frozenset({"src", "tests", "docs"})


@dataclass(frozen=True)
class RunTarget:
    """How run-smoke invokes the deliverable.

    `kind` selects the argv shape; `target` is the `-m` package/module name
    for `module`, or the script path (relative to the project root, posix
    form) for `script`. Frozen so a resolved target cannot be mutated
    between resolution and argv assembly.
    """

    kind: Literal["module", "script"]
    target: str


def resolve_pkg(
    root: Path,
    script_candidates: tuple[str, ...] | list[str] = _DEFAULT_SCRIPT_CANDIDATES,
) -> RunTarget:
    """Resolve the project's run-smoke target as a `RunTarget(kind, target)`.

    `script_candidates` is the ordered root-entry-script filename list (the
    lowest rung) — supplied by the adapter from config so no magic list lives
    here. Raises `ValueError` on ambiguity at any rung or absence of all rungs
    (never guesses).
    """
    declared = _from_pyproject(root)
    if declared is not None:
        return RunTarget(kind="module", target=declared)

    root_pkg = _single_root_package(root)
    if root_pkg is not None:
        return RunTarget(kind="module", target=root_pkg)

    src = root / "src"
    if src.is_dir():
        pkg = _single_src_package(src)
        if pkg is not None:
            return RunTarget(kind="module", target=pkg)

    script = _single_root_script(root, tuple(script_candidates))
    if script is not None:
        return RunTarget(kind="script", target=script)

    raise ValueError(
        f"cannot resolve a python-cli run target under {root}: no hatchling wheel "
        "target, [project.scripts] entry, root/src package, or root entry script found"
    )


def _from_pyproject(root: Path) -> str | None:
    """The single declared `-m` target from pyproject, or None.

    Reads the hatchling wheel target first, then a single `[project.scripts]`
    console entry. A declared-but-ambiguous rung (>1 wheel target, >1 console
    entry) RAISES `ValueError` so the caller never guesses the intent. The
    try/except only swallows TOML-parse and I/O errors — an unreadable /
    malformed pyproject returns None (treated as "no declared target", fall
    through to filesystem discovery), never a crash. None therefore means
    "nothing declared", never "declared but ambiguous".
    """
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None

    hatch = _hatchling_target(data)
    if hatch is not None:
        return hatch
    return _scripts_entry_module(data)


def _hatchling_target(data: dict[str, object]) -> str | None:
    """The `-m` module from a single hatchling wheel target, or None."""
    packages = _dig(data, "tool", "hatch", "build", "targets", "wheel", "packages")
    if not isinstance(packages, list) or not packages:
        return None
    if len(packages) != 1:
        raise ValueError("ambiguous hatchling wheel target: more than one package declared")
    entry = packages[0]
    if not isinstance(entry, str):
        return None
    # "src/<pkg>" → "<pkg>"; a bare "<pkg>" → "<pkg>".
    return Path(entry).name or None


def _scripts_entry_module(data: dict[str, object]) -> str | None:
    """The `-m` module from a single `[project.scripts]` console entry, or None.

    The entry value is `module.path:callable`; the module is the `-m` target.
    More than one entry is ambiguous → raise (declared but no single intent).
    """
    scripts = _dig(data, "project", "scripts")
    if not isinstance(scripts, dict) or not scripts:
        return None
    if len(scripts) != 1:
        raise ValueError("ambiguous [project.scripts]: more than one console entry declared")
    value = next(iter(scripts.values()))
    if not isinstance(value, str):
        return None
    module = value.split(":", 1)[0].strip()
    return module or None


def _dig(data: dict[str, object], *keys: str) -> object:
    """Walk nested dicts by `keys`; return None if any level is missing."""
    cur: object = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _single_root_package(root: Path) -> str | None:
    """Name of the single root-level package with `__main__.py`, or None.

    A root package is a directory with `__init__.py`. Only a `__main__.py`-
    bearing one is `-m`-runnable; >1 such → ambiguous → raise. Reserved
    container/scaffold dirs (`src`, `tests`, `docs`) are excluded so a
    confused scaffold can never resolve to `python -m src`.
    """
    runnable = [
        child.name
        for child in sorted(root.iterdir())
        if child.is_dir()
        and child.name not in _RESERVED_ROOT_DIRS
        and (child / "__init__.py").is_file()
        and (child / "__main__.py").is_file()
    ]
    if not runnable:
        return None
    if len(runnable) > 1:
        raise ValueError(f"ambiguous root packages with __main__.py: {runnable}")
    return runnable[0]


def _single_src_package(src: Path) -> str | None:
    """Name of the single runnable package under `src/`, or None.

    Symmetric with every other rung: a sole candidate package is the target;
    among multiple candidates, only a UNIQUE `__main__.py`-runnable one is
    picked. Multiple candidates with zero or >1 runnable is genuine ambiguity
    → raise (never silently pick one runnable among several candidate packages,
    which would run the wrong package when a sibling carries a stray
    `__main__.py`).
    """
    candidates = [
        child
        for child in sorted(src.iterdir())
        if child.is_dir() and (child / "__init__.py").is_file()
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0].name
    runnable = [c for c in candidates if (c / "__main__.py").is_file()]
    if len(runnable) == 1:
        return runnable[0].name
    raise ValueError(
        f"ambiguous src packages: {[c.name for c in candidates]} "
        "(no unique __main__.py-runnable package)"
    )


def _single_root_script(root: Path, candidates: tuple[str, ...]) -> str | None:
    """The single root entry script from the ordered candidate list, or None.

    The lowest precedence rung — a bare script is the weakest declaration of
    intent. More than one candidate present → ambiguous → raise (never pick
    one by candidate order; the order documents precedence only when exactly
    one exists, so two present is a genuine ambiguity the user must resolve).
    Non-simple names (containing `/` or `..`, i.e. anything that could resolve
    outside the project root) are skipped defensively — the config validator
    rejects them at load time, this is the second line of defence so a
    traversal candidate can never resolve to a runnable path.
    """
    present = [
        name
        for name in candidates
        if name not in {".", ".."} and Path(name).name == name and (root / name).is_file()
    ]
    if not present:
        return None
    if len(present) > 1:
        raise ValueError(f"ambiguous root entry scripts: {present}")
    return present[0]

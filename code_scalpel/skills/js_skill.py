"""JsTsSkill — npm/pnpm/yarn defaults for a Node.js / TypeScript project.

Detection is `package.json` plus one of the well-known lockfiles. The
lockfile picks the package manager so we don't blindly assume `npm`:
modern repos lean heavily on pnpm and yarn.

Commands assume the project follows the `package.json` `scripts.test` /
`scripts.lint` / `scripts.format` convention — the most common shape.
Projects that diverge wire their own skill via `register_skill`.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from code_scalpel.skills.base import Skill


def _detect_pm(root: Path) -> str:
    """Pick the package manager from the lockfile that's present.
    pnpm-lock takes priority over yarn.lock takes priority over
    package-lock.json — matches what most multi-PM repos imply when
    they accidentally check in more than one (the newer manager won)."""
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    return "npm"  # default — works even without a lockfile present


class JsTsSkill(Skill):
    name = "js"
    description = (
        "npm/pnpm/yarn test/lint/format for a JavaScript or TypeScript project "
        "(detects package.json)."
    )

    def detect(self, root: Path) -> bool:
        return (root / "package.json").is_file()

    def test_cmd(self, args: str = "") -> list[str]:
        pm = _detect_pm(Path.cwd())
        extra = shlex.split(args) if args else []
        # `npm test --` injects extra args correctly via the `--` divider;
        # pnpm/yarn accept the same idiom.
        if extra:
            return [pm, "test", "--", *extra]
        return [pm, "test"]

    def lint_cmd(self) -> list[str]:
        pm = _detect_pm(Path.cwd())
        return [pm, "run", "lint"]

    def format_cmd(self) -> list[str] | None:
        pm = _detect_pm(Path.cwd())
        return [pm, "run", "format"]

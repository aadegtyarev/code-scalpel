"""Prompt loader — every text string the agent sends to the LLM lives as a
.md file under this package, not as a Python triple-quoted constant.

Why on disk:
- Edits don't need a Python diff; reviewers can read prompts as docs.
- Per-mode files (system/mode_code/mode_plan/mode_review) keep each
  body small and focused — no scrolling past 200 lines of one constant
  to find the one rule you wanted to tweak.
- Retry prompts live in `retry/` because they're parameterised at use
  time (`.format(error=…)`) and form a natural sub-namespace.

Loaded eagerly at import: there are <10 files, all tiny, and the
agent fires them on every turn — no point in caching laziness.
"""

from __future__ import annotations

from importlib.resources import files


def _load(name: str) -> str:
    """Read a prompt file from this package's resources, strip the trailing
    newline that every editor adds. Returns the body verbatim."""
    return files(__name__).joinpath(name).read_text().rstrip("\n")


SYSTEM = _load("system.md")
MODE_CODE = _load("mode_code.md")
MODE_PLAN = _load("mode_plan.md")
MODE_REVIEW = _load("mode_review.md")
ANNOTATE_SKILLS = _load("annotate_skills.md")

APPLY_FAILED = _load("retry/apply_failed.md")
TESTS_FAILED = _load("retry/tests_failed.md")
MISSING_FILES = _load("retry/missing_files.md")
NEEDS_TESTS = _load("retry/needs_tests.md")
READ_BEFORE_SHOW = _load("retry/read_before_show.md")
FORCE_ANSWER = _load("retry/force_answer.md")


__all__ = [
    "ANNOTATE_SKILLS",
    "APPLY_FAILED",
    "FORCE_ANSWER",
    "MISSING_FILES",
    "MODE_CODE",
    "MODE_PLAN",
    "MODE_REVIEW",
    "NEEDS_TESTS",
    "READ_BEFORE_SHOW",
    "SYSTEM",
    "TESTS_FAILED",
]

from __future__ import annotations

import re

import unidiff

_FENCE_RE = re.compile(r"```diff\n(.*?)```", re.DOTALL)
_HEADER_RE = re.compile(r"(diff --git .+)", re.DOTALL)


def extract_patch(text: str) -> str | None:
    """Extract unified diff from LLM output. Returns raw patch string or None."""
    # Prefer fenced code block
    m = _FENCE_RE.search(text)
    if m:
        candidate = m.group(1)
        if _is_valid(candidate):
            return candidate

    # Fall back to bare diff header
    m2 = _HEADER_RE.search(text)
    if m2:
        candidate = text[m2.start() :]
        if _is_valid(candidate):
            return candidate

    return None


def _is_valid(patch: str) -> bool:
    try:
        parsed = unidiff.PatchSet(patch)
        return len(parsed) > 0
    except Exception:
        return False


def parse_patch(patch: str) -> unidiff.PatchSet:
    """Parse validated patch string into PatchSet."""
    return unidiff.PatchSet(patch)

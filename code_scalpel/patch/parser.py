from __future__ import annotations

import re

import unidiff

from code_scalpel.patch.normalizer import fix_hunk_headers

_FENCE_RE = re.compile(r"```diff\n(.*?)```", re.DOTALL)
_HEADER_RE = re.compile(r"(diff --git .+)", re.DOTALL)


def extract_patch(text: str) -> str | None:
    """Extract unified diff from LLM output. Returns normalized patch or None.

    Normalizes hunk headers so git apply accepts patches where the LLM
    miscounted context lines (common with blank lines between hunks).
    """
    candidate = _find_candidate(text)
    if candidate is None:
        return None
    normalized = fix_hunk_headers(candidate)
    if _is_valid(normalized):
        return normalized
    return None


def _find_candidate(text: str) -> str | None:
    m = _FENCE_RE.search(text)
    if m:
        candidate = m.group(1)
        if "---" in candidate and "+++" in candidate:
            return candidate
    m2 = _HEADER_RE.search(text)
    if m2:
        return text[m2.start() :]
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

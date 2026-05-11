"""Keyword-ranked symbol search across `FileIndex` outputs.

Fills the gap between `goto_definition` (exact name only) and `grep`
(every textual hit including comments and docs). Splits the query into
word tokens and scores each symbol on two tracks:

  * name / qualified_name match — +2 per token hit (strong signal)
  * docstring match — +1 per token hit (weaker signal)

Symbols with a zero score are dropped; the rest are sorted by score
desc, ties broken by lineno asc within the same file. Top `k` rows are
returned. Pure-Python, no embeddings, no extra dependencies — runs on
demand off the same `build_file_index` infra Phase 3 already gave us.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from code_scalpel.index.builder import build_file_index
from code_scalpel.index.model import Symbol
from code_scalpel.tools.files import list_files

_TOKEN_RE = re.compile(r"\w+")
_NAME_WEIGHT = 2
_DOC_WEIGHT = 1
_MAX_FILES = 200


@dataclass(frozen=True)
class Hit:
    """One ranked match from `search`.

    Carries enough columns to render the same `path:line  kind
    qualified_name  · docstring` row the agent tool prints. Score is
    surfaced so callers can debug ranking without re-running the scorer.
    """

    rel_path: str
    lineno: int
    kind: str
    qualified_name: str
    docstring: str
    score: float


def _tokenize(query: str) -> list[str]:
    """Split `query` on whitespace + punctuation, lowercase each token.

    `re.findall(r"\\w+")` is the same rule the docstring talks about —
    matches the contract the tests assert against.
    """
    return _TOKEN_RE.findall(query.lower())


def _score_symbol(symbol: Symbol, tokens: list[str]) -> float:
    """Two-track scoring: name hits are worth `_NAME_WEIGHT`, docstring
    hits `_DOC_WEIGHT`. Multiple tokens stack — query `"context
    compression"` rewards symbols that mention both."""
    name_blob = f"{symbol.name} {symbol.qualified_name}".lower()
    doc_blob = symbol.docstring.lower()
    score = 0.0
    for tok in tokens:
        if tok in name_blob:
            score += _NAME_WEIGHT
        if doc_blob and tok in doc_blob:
            score += _DOC_WEIGHT
    return score


def search(
    root: Path,
    query: str,
    *,
    path: str | None = None,
    k: int = 10,
) -> tuple[Hit, ...]:
    """Search the project (or one file) for symbols matching `query`.

    `path` scopes the walk to a single Python file — useful when the
    caller already knows which file to drill into. Without it we walk
    every Python file under `root` (capped at `_MAX_FILES`, same budget
    as the project map). Non-Python files are skipped silently; the
    walk never raises on a bad file.
    """
    tokens = _tokenize(query)
    if not tokens:
        return ()

    if path is not None:
        rel_paths: list[str] = [path]
    else:
        rel_paths = [str(p) for p in list_files(root, max_files=_MAX_FILES)]

    hits: list[Hit] = []
    for rel in rel_paths:
        if not rel.endswith(".py"):
            continue
        idx = build_file_index(root, rel)
        if idx is None:
            continue
        for sym in idx.symbols:
            score = _score_symbol(sym, tokens)
            if score <= 0:
                continue
            hits.append(
                Hit(
                    rel_path=idx.rel_path,
                    lineno=sym.lineno,
                    kind=sym.kind,
                    qualified_name=sym.qualified_name,
                    docstring=sym.docstring,
                    score=score,
                )
            )

    # Sort by score desc; deterministic tie-break by (rel_path, lineno)
    # so the same query always returns the same ordering.
    hits.sort(key=lambda h: (-h.score, h.rel_path, h.lineno))
    return tuple(hits[:k])

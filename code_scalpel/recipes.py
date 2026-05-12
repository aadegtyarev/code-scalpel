"""Load `/learn`-generated recipes back into the agent's context.

Closes the loop that `/learn` left open: it wrote a recipe markdown to
`.code-scalpel/recipes/<name>.md` but the agent had no way to see it
on the next turn. Now `eager_recipes(cwd)` finds every recipe with
`load: eager` in its YAML frontmatter and `format_recipes_block`
renders them as a labelled block prepended to the user message,
right next to the memory-recall block. The model sees the recipes
as part of the turn's prompt — same channel, same shape.

Scope of this v0.5 MVP:
  • project-local `.code-scalpel/recipes/` only. Plan §22 also names
    user (`~/.config/code-scalpel/recipes/`) and built-in
    (`code_scalpel/recipes/`) directories — those follow when there's
    actual demand.
  • `load: eager` only. Lazy keyword-matched loading is part of the
    plan; ships when we have data on what real recipe bodies look
    like and whether per-turn keyword scoring is worth the cost.
  • Body is included verbatim, no LLM re-summarisation. The recipe
    file is the source of truth; the user curated it (or `/learn`
    generated it and the user accepted as-is).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass(frozen=True)
class Recipe:
    """Parsed recipe — frontmatter fields + body. Unknown frontmatter
    keys are ignored (forward-compatible: a future field can land in
    the file without breaking older code)."""

    name: str
    load: str  # "eager" | "lazy"
    body: str
    keywords: tuple[str, ...] = field(default_factory=tuple)


def parse_recipe(text: str) -> Recipe | None:
    """Parse a recipe markdown file with YAML frontmatter.

    Returns `None` (rather than raising) for any non-recipe shape —
    no frontmatter fence, malformed YAML, missing `name`, etc. A
    broken file in `.code-scalpel/recipes/` must NOT block every
    turn; we just drop it from the load set."""
    m = _FRONTMATTER_RE.match(text)
    if m is None:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    name = str(meta.get("name", "")).strip()
    if not name:
        return None
    load = str(meta.get("load", "eager")).strip().lower()
    if load not in ("eager", "lazy"):
        # Unknown load mode → treat as eager. Forward-compat: if a
        # future recipe declares `load: project_only`, we'd rather
        # show it than silently drop it.
        load = "eager"
    raw_keywords = meta.get("keywords") or []
    if not isinstance(raw_keywords, list):
        raw_keywords = []
    keywords = tuple(str(k) for k in raw_keywords if isinstance(k, str))
    body = m.group(2).strip()
    return Recipe(name=name, load=load, body=body, keywords=keywords)


def discover_recipes(cwd: Path) -> list[Recipe]:
    """Return every parsable recipe under `.code-scalpel/recipes/` in
    `cwd`, sorted by file name for a stable order in the prompt.
    Files that don't parse are silently skipped."""
    root = cwd / ".code-scalpel" / "recipes"
    if not root.is_dir():
        return []
    recipes: list[Recipe] = []
    for path in sorted(root.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parsed = parse_recipe(text)
        if parsed is not None:
            recipes.append(parsed)
    return recipes


def eager_recipes(cwd: Path) -> list[Recipe]:
    """Recipes with `load: eager`. Prepended to every user message."""
    return [r for r in discover_recipes(cwd) if r.load == "eager"]


def format_recipes_block(recipes: list[Recipe]) -> str:
    """Render recipes as a labelled block for prompt injection. Empty
    string when the list is empty so callers can `if block: …`."""
    if not recipes:
        return ""
    parts = ["Loaded recipes (from .code-scalpel/recipes/):"]
    for r in recipes:
        parts.append(f"\n### {r.name}\n{r.body}")
    return "\n".join(parts)

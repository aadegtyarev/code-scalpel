"""Load `/learn`-generated recipes back into the agent's context.

`/learn` writes a recipe markdown to `.code-scalpel/recipes/<name>.md`;
this module reads them back so the agent sees the knowledge on every
turn. Two loading modes:

  • **eager** — surfaced on EVERY turn, regardless of task content.
    Use for core stack info ("we test with pytest", "our Python is
    typed everywhere") that's relevant always.
  • **lazy** — surfaced only when the user's task text contains one
    of the recipe's `keywords`. Use for component-specific knowledge
    ("redis commands", "k8s manifests") that matters only on
    relevant turns. Case-insensitive substring match on the raw
    task text (the agent doesn't have to remember keywords; the
    user's natural phrasing triggers).

Three discovery directories, in priority order — project beats user
beats built-in. Same `name` in two dirs → project wins:

  1. `<cwd>/.code-scalpel/recipes/`
  2. `~/.config/code-scalpel/recipes/`
  3. `<package>/recipes/` (bundled, ships with the agent)

Bodies are included verbatim — the recipe file is source of truth,
no LLM re-summarisation involved.
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


def _builtin_recipes_dir() -> Path:
    """Path to bundled recipes that ship with the agent (next to this
    module). Empty in fresh installs; populated only when we curate
    starter recipes — same lookup mechanism either way."""
    return Path(__file__).parent / "recipes_builtin"


def _user_recipes_dir() -> Path:
    """`~/.config/code-scalpel/recipes/` — user-level recipes that
    follow the user across projects. Standard XDG-style path."""
    return Path.home() / ".config" / "code-scalpel" / "recipes"


def _scan_dir(root: Path) -> list[Recipe]:
    """Parse every `*.md` under `root` (non-recursive). Files that
    don't parse are silently skipped; missing dir → empty list."""
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


def discover_recipes(cwd: Path) -> list[Recipe]:
    """Return every parsable recipe across the three discovery dirs
    (project > user > built-in), deduped by `name`. Same `name`
    appearing in multiple dirs → the highest-priority copy wins
    (project beats user beats built-in). Results are sorted by name
    for stable prompt ordering."""
    project = cwd / ".code-scalpel" / "recipes"
    seen: dict[str, Recipe] = {}
    # Highest priority first; later writes are silently skipped.
    for source in (project, _user_recipes_dir(), _builtin_recipes_dir()):
        for r in _scan_dir(source):
            seen.setdefault(r.name, r)
    return sorted(seen.values(), key=lambda r: r.name)


def eager_recipes(cwd: Path) -> list[Recipe]:
    """Recipes with `load: eager`. Prepended to every user message."""
    return [r for r in discover_recipes(cwd) if r.load == "eager"]


def lazy_recipes_for(cwd: Path, task: str) -> list[Recipe]:
    """Recipes with `load: lazy` whose `keywords` match `task` text.

    Match is case-insensitive substring — the keyword has to appear
    somewhere in the lowered task string. No regex, no word boundary —
    a recipe keyworded `["redis"]` triggers on `redis-py`, `Redis`,
    `using Redis`, all of which are valid signals.
    """
    if not task:
        return []
    lower = task.lower()
    hits: list[Recipe] = []
    for r in discover_recipes(cwd):
        if r.load != "lazy":
            continue
        if any(k and k.lower() in lower for k in r.keywords):
            hits.append(r)
    return hits


def recipes_for_turn(cwd: Path, task: str) -> list[Recipe]:
    """Combined set surfaced for this turn: eager + lazy-matched.
    Deduped by name (a recipe shouldn't appear twice if it's both
    eager and lazy-matched somehow). Stable order by name."""
    seen: dict[str, Recipe] = {}
    for r in eager_recipes(cwd):
        seen.setdefault(r.name, r)
    for r in lazy_recipes_for(cwd, task):
        seen.setdefault(r.name, r)
    return sorted(seen.values(), key=lambda r: r.name)


def format_recipes_block(recipes: list[Recipe]) -> str:
    """Render recipes as a labelled block for prompt injection. Empty
    string when the list is empty so callers can `if block: …`."""
    if not recipes:
        return ""
    parts = ["Loaded recipes:"]
    for r in recipes:
        parts.append(f"\n### {r.name}\n{r.body}")
    return "\n".join(parts)

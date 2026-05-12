"""`/learn` — generate a recipe or skill markdown file from model knowledge.

A **recipe** captures knowledge about a technology (how to run tests, lint,
key commands, conventions). A **skill** captures a step-by-step approach to
a class of task ("how to think when adding tests"). Both are markdown files
with YAML frontmatter, saved under `.code-scalpel/recipes/` or `.code-scalpel/skills/`.

v0.3 MVP — runtime integration (loading these back into the agent's context
on relevant turns) is future work. For now `/learn` produces the file; the
user curates and the existence of the file is the contract.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from code_scalpel.fetch import fetch_markdown
from code_scalpel.runtime import Runtime

Kind = Literal["recipe", "skill"]

_RECIPE_PROMPT = """\
Generate a code-scalpel recipe for `{name}`. A recipe captures knowledge
about a technology — how to run its tests, lint it, the commands the
agent is allowed to call, important conventions.

Output ONLY the markdown file body, starting at column 0. No prose
before or after, no triple-backtick fence around the whole thing. The
exact shape:

---
name: {name}
load: lazy
keywords: ["keyword1", "keyword2"]
file_patterns: ["..."]
test_cmd: ["..."]
lint_cmds: [["..."]]
allowed_commands: ["..."]
---

# {name}
- short, actionable bullet about a convention
- another bullet

`load: lazy` means this recipe is injected only when the user's task
mentions one of the keywords. Pick 2–5 keywords that would naturally
appear when someone starts working with `{name}` — tool name, common
command names, framework terms. Keep them short (one word is fine).

Drop fields that don't apply (e.g. omit `test_cmd:` if the tech has no
test runner). Keep the body under twenty bullets — this is a hint sheet
for the agent, not a tutorial.
"""

_SKILL_PROMPT = """\
Generate a code-scalpel skill for `{name}`. A skill is a step-by-step
approach to a class of task — how the agent should think when doing X.
No commands, no tool config; pure procedure.

Output ONLY the markdown file body, starting at column 0. No prose
before or after, no triple-backtick fence around the whole thing. The
exact shape:

---
name: {name}
triggers: ["keyword1", "keyword2"]
---

# {name}
1. First concrete step
2. Second step
3. ...

`triggers` is a small list of literal substrings that a user task
might contain to imply "do {name} now". Keep the procedure under ten
steps and bias towards verbs, not theory.
"""

_URL_PREAMBLE = """\
The following markdown was extracted from `{url}`. Use it as the
primary source of truth for the recipe/skill body. Where the page
covers things outside the scope of a code-scalpel recipe/skill,
just drop them — don't pad.

----- BEGIN FETCHED CONTENT -----
{content}
----- END FETCHED CONTENT -----

Now produce the markdown file as instructed below.
"""

_FRONTMATTER_FENCE = "---"


def _safe_filename(name: str) -> str:
    """Convert `name` into a safe filename stem.

    Two passes: (1) any path-traversal token (`..`) or path separator becomes
    `_` — keeps the recipe inside `.code-scalpel/recipes/` no matter what the
    user typed; (2) everything that isn't alphanum, underscore, dash, or
    a single dot becomes `_`, then collapse runs of `_`. Empty result →
    fallback so `learn("")` doesn't write `.md` with no stem.
    """
    no_traversal = re.sub(r"\.{2,}|[/\\]", "_", name)
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", no_traversal)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "untitled"


def _strip_fences(text: str) -> str:
    """Some models wrap the whole reply in ```markdown ... ``` despite being
    told not to. Strip a single outer fence if present — leave inner
    fences (real markdown code blocks in the recipe body) alone."""
    stripped = text.strip()
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip() + "\n"
    return stripped + "\n"


def _target_dir(cwd: Path, kind: Kind) -> Path:
    # `recipes` / `skills` — plural — matches the discovery convention
    # in docs/plan.md §22.
    return cwd / ".code-scalpel" / f"{kind}s"


async def learn(
    runtime: Runtime,
    name: str,
    *,
    kind: Kind = "recipe",
    url: str | None = None,
) -> Path:
    """Ask the model for a recipe/skill on `name`, save to disk, return path.

    With `url`, fetch the page and feed its markdown-converted body into
    the prompt as authoritative source — the model summarises the doc
    rather than guessing from training. Without `url`, the model writes
    from its own knowledge.

    Overwrites existing files at the same path — the user controls naming
    and re-running `/learn foo` is the intended "regenerate" path. If the
    model returns an empty reply, raises `RuntimeError` instead of writing
    an empty file. Fetch errors propagate as `RuntimeError` (see
    `code_scalpel.fetch`)."""
    template = _RECIPE_PROMPT if kind == "recipe" else _SKILL_PROMPT
    prompt = template.format(name=name)
    if url is not None:
        content = await fetch_markdown(url)
        prompt = _URL_PREAMBLE.format(url=url, content=content) + "\n" + prompt
    result = await runtime.ask(prompt, mode="ask")
    body = _strip_fences(result.reply)
    if not body.strip() or _FRONTMATTER_FENCE not in body:
        raise RuntimeError(f"Model returned no usable {kind} body — got {result.reply[:120]!r}")
    target_dir = _target_dir(runtime.cwd, kind)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{_safe_filename(name)}.md"
    target.write_text(body)
    return target

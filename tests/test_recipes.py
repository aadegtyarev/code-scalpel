"""recipes.py — discover + parse + format /learn-generated recipes.

Tests pin the contract: a recipe with `load: eager` is surfaced in
the agent's user message; malformed files are silently skipped (no
broken file blocks every turn); body is rendered verbatim.
"""

from __future__ import annotations

from pathlib import Path

from code_scalpel.recipes import (
    Recipe,
    discover_recipes,
    eager_recipes,
    format_recipes_block,
    parse_recipe,
)


def test_parse_recipe_happy_path() -> None:
    text = (
        "---\n"
        "name: redis\n"
        "load: lazy\n"
        'file_patterns: ["*.py"]\n'
        'keywords: ["redis", "cache"]\n'
        "---\n"
        "\n"
        "# redis\n"
        "- SET key value\n"
    )
    r = parse_recipe(text)
    assert r is not None
    assert r.name == "redis"
    assert r.load == "lazy"
    assert r.keywords == ("redis", "cache")
    assert "SET key value" in r.body


def test_parse_recipe_defaults_load_to_eager() -> None:
    """`load:` field is optional — default eager."""
    text = "---\nname: python\n---\n\n# python\n- bullet\n"
    r = parse_recipe(text)
    assert r is not None
    assert r.load == "eager"


def test_parse_recipe_unknown_load_falls_back_to_eager() -> None:
    """Forward-compat: a future `load: per_skill` shouldn't drop the
    recipe. Treat anything we don't recognise as eager."""
    text = "---\nname: x\nload: per_skill\n---\n\n# x\n"
    r = parse_recipe(text)
    assert r is not None
    assert r.load == "eager"


def test_parse_recipe_without_frontmatter_returns_none() -> None:
    assert parse_recipe("# just a header\n\nno frontmatter\n") is None


def test_parse_recipe_without_name_returns_none() -> None:
    """The `name` field is the only required one — without it the
    recipe can't be addressed or labelled, so drop it."""
    text = "---\nload: eager\n---\n\n# anon\n"
    assert parse_recipe(text) is None


def test_parse_recipe_malformed_yaml_returns_none() -> None:
    """Broken YAML in one file must NOT block other recipes — the
    parser returns None so the discovery loop skips it."""
    text = "---\nname: bad\n  load: eager\n bad indent\n---\n\n# bad\n"
    assert parse_recipe(text) is None


def test_parse_recipe_keywords_filters_non_strings() -> None:
    """If `keywords: [foo, 42, true]` (mixed types), only the string
    entries survive — defensive against `/learn` output drift."""
    text = "---\nname: x\nkeywords: [foo, 42, bar]\n---\n\n# x\n"
    r = parse_recipe(text)
    assert r is not None
    assert r.keywords == ("foo", "bar")


def test_discover_recipes_returns_empty_when_no_dir(tmp_path: Path) -> None:
    """Project without `.code-scalpel/recipes/` → empty list, no error.
    The vast majority of projects start this way; the discovery path
    must be a silent no-op for them."""
    assert discover_recipes(tmp_path) == []


def test_discover_recipes_reads_files_alphabetically(tmp_path: Path) -> None:
    """Order matters for prompt stability — same inputs, same prompt
    bytes, KV-cache stays warm. Sort by filename, not by mtime or
    arbitrary FS order."""
    rdir = tmp_path / ".code-scalpel" / "recipes"
    rdir.mkdir(parents=True)
    (rdir / "z.md").write_text("---\nname: z\n---\n\n# z\n")
    (rdir / "a.md").write_text("---\nname: a\n---\n\n# a\n")
    (rdir / "m.md").write_text("---\nname: m\n---\n\n# m\n")

    names = [r.name for r in discover_recipes(tmp_path)]
    assert names == ["a", "m", "z"]


def test_discover_recipes_skips_malformed(tmp_path: Path) -> None:
    """A broken recipe must NOT block the good ones from loading."""
    rdir = tmp_path / ".code-scalpel" / "recipes"
    rdir.mkdir(parents=True)
    (rdir / "good.md").write_text("---\nname: good\n---\n\n# good\n")
    (rdir / "bad.md").write_text("# no frontmatter here\n")

    names = [r.name for r in discover_recipes(tmp_path)]
    assert names == ["good"]


def test_eager_recipes_filters_lazy_ones(tmp_path: Path) -> None:
    rdir = tmp_path / ".code-scalpel" / "recipes"
    rdir.mkdir(parents=True)
    (rdir / "py.md").write_text("---\nname: python\nload: eager\n---\n\n# python\n")
    (rdir / "redis.md").write_text("---\nname: redis\nload: lazy\n---\n\n# redis\n")

    names = [r.name for r in eager_recipes(tmp_path)]
    assert names == ["python"]


def test_format_recipes_block_renders_bodies() -> None:
    recipes = [
        Recipe(name="python", load="eager", body="# python\n- ты"),
        Recipe(name="git", load="eager", body="# git\n- ветки"),
    ]
    block = format_recipes_block(recipes)
    assert block.startswith("Loaded recipes")
    assert "### python" in block
    assert "### git" in block
    assert "# python\n- ты" in block
    assert "# git\n- ветки" in block


def test_format_recipes_block_empty_for_no_recipes() -> None:
    """Empty list → empty string. Caller does `if block:` to skip."""
    assert format_recipes_block([]) == ""

"""recipes.py — discover + parse + format /learn-generated recipes.

Tests pin the contract: a recipe with `load: eager` is surfaced in
the agent's user message; malformed files are silently skipped (no
broken file blocks every turn); body is rendered verbatim.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.recipes import (
    Recipe,
    discover_recipes,
    eager_recipes,
    format_recipes_block,
    lazy_recipes_for,
    parse_recipe,
    recipes_for_turn,
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


# ── lazy / multi-dir ─────────────────────────────────────────────────────────


@pytest.fixture
def isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """Three real directories with no shared state — project, user, built-in.
    User HOME and the bundled-recipes path are both redirected so a real
    install can't leak in from the developer's actual home directory."""
    project = tmp_path / "project"
    user = tmp_path / "user_home"
    builtin = tmp_path / "package_recipes"
    for d in (project, user, builtin):
        d.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setattr("code_scalpel.recipes._builtin_recipes_dir", lambda: builtin)
    return project, user, builtin


def _write_recipe(dir_path: Path, filename: str, body: str) -> None:
    """Write `body` to `dir_path/<filename>`, creating subdirs as needed."""
    target = dir_path / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)


def test_lazy_recipe_surfaces_on_keyword_hit(tmp_path: Path) -> None:
    """A `load: lazy` recipe with `keywords: [redis]` shows up only when
    the task mentions redis."""
    _write_recipe(
        tmp_path / ".code-scalpel" / "recipes",
        "redis.md",
        "---\nname: redis\nload: lazy\nkeywords: [redis, cache]\n---\n\n# redis\n- SET\n",
    )

    hits = lazy_recipes_for(tmp_path, "how do I use redis here?")
    assert [r.name for r in hits] == ["redis"]


def test_lazy_recipe_case_insensitive(tmp_path: Path) -> None:
    """Substring match is case-insensitive — `Redis`, `REDIS`, `redis-py`
    all trigger a `keywords: [redis]` recipe."""
    _write_recipe(
        tmp_path / ".code-scalpel" / "recipes",
        "redis.md",
        "---\nname: redis\nload: lazy\nkeywords: [redis]\n---\n\n# r\n",
    )

    assert lazy_recipes_for(tmp_path, "using Redis here") == lazy_recipes_for(
        tmp_path, "using REDIS here"
    )
    assert lazy_recipes_for(tmp_path, "redis-py setup") != []


def test_lazy_recipe_skipped_on_no_keyword_hit(tmp_path: Path) -> None:
    """No match → no surface. The whole point of lazy is to keep
    irrelevant recipes out of the prompt."""
    _write_recipe(
        tmp_path / ".code-scalpel" / "recipes",
        "redis.md",
        "---\nname: redis\nload: lazy\nkeywords: [redis]\n---\n\n# r\n",
    )
    assert lazy_recipes_for(tmp_path, "what does pytest do?") == []


def test_lazy_recipe_with_no_keywords_never_surfaces(tmp_path: Path) -> None:
    """`load: lazy` with empty `keywords` is a no-op — nothing to match
    against. Validates that we don't accidentally fall through to a
    keyword-less catch-all."""
    _write_recipe(
        tmp_path / ".code-scalpel" / "recipes",
        "x.md",
        "---\nname: x\nload: lazy\n---\n\n# x\n",
    )
    assert lazy_recipes_for(tmp_path, "anything goes here redis") == []


def test_eager_recipes_ignored_by_lazy_lookup(tmp_path: Path) -> None:
    """`eager_recipes` and `lazy_recipes_for` are disjoint — an
    eager recipe never shows up in the lazy lookup even if its
    body contains keyword-like text."""
    _write_recipe(
        tmp_path / ".code-scalpel" / "recipes",
        "redis.md",
        "---\nname: redis\nload: eager\nkeywords: [redis]\n---\n\n# r\n",
    )
    assert lazy_recipes_for(tmp_path, "redis here") == []
    assert [r.name for r in eager_recipes(tmp_path)] == ["redis"]


def test_recipes_for_turn_combines_eager_and_lazy_match(tmp_path: Path) -> None:
    """`recipes_for_turn` is what `_user_message` calls — must
    return eager (always) + lazy hits, deduped by name, sorted."""
    _write_recipe(
        tmp_path / ".code-scalpel" / "recipes",
        "python.md",
        "---\nname: python\nload: eager\n---\n\n# python\n",
    )
    _write_recipe(
        tmp_path / ".code-scalpel" / "recipes",
        "redis.md",
        "---\nname: redis\nload: lazy\nkeywords: [redis]\n---\n\n# r\n",
    )
    _write_recipe(
        tmp_path / ".code-scalpel" / "recipes",
        "k8s.md",
        "---\nname: k8s\nload: lazy\nkeywords: [kubernetes, kubectl]\n---\n\n# k\n",
    )

    # Task mentions redis only → python (eager) + redis (lazy).
    names = [r.name for r in recipes_for_turn(tmp_path, "set up redis caching")]
    assert names == ["python", "redis"]

    # Task mentions kubectl → python (eager) + k8s (lazy).
    names = [r.name for r in recipes_for_turn(tmp_path, "kubectl apply")]
    assert names == ["k8s", "python"]


def test_discover_merges_all_three_dirs(
    isolated_dirs: tuple[Path, Path, Path],
) -> None:
    """Recipes from project, user (~/.config/code-scalpel/recipes/), and
    built-in (bundled in package) all surface in `discover_recipes`."""
    project, user, builtin = isolated_dirs
    _write_recipe(
        project / ".code-scalpel" / "recipes",
        "proj.md",
        "---\nname: proj\n---\n\n# p\n",
    )
    _write_recipe(
        user / ".config" / "code-scalpel" / "recipes",
        "usr.md",
        "---\nname: usr\n---\n\n# u\n",
    )
    _write_recipe(builtin, "builtin.md", "---\nname: builtin\n---\n\n# b\n")

    names = [r.name for r in discover_recipes(project)]
    assert names == ["builtin", "proj", "usr"]


def test_project_wins_over_user_and_builtin_on_name_collision(
    isolated_dirs: tuple[Path, Path, Path],
) -> None:
    """Same `name:` in two dirs → highest-priority wins (project >
    user > built-in). User customises a built-in by writing
    their own; project overrides both."""
    project, user, builtin = isolated_dirs
    _write_recipe(
        project / ".code-scalpel" / "recipes",
        "python.md",
        "---\nname: python\n---\n\n# project version\n",
    )
    _write_recipe(
        user / ".config" / "code-scalpel" / "recipes",
        "python.md",
        "---\nname: python\n---\n\n# user version\n",
    )
    _write_recipe(builtin, "python.md", "---\nname: python\n---\n\n# builtin version\n")

    recipes = discover_recipes(project)
    assert len(recipes) == 1
    assert recipes[0].name == "python"
    assert "project version" in recipes[0].body
    assert "user version" not in recipes[0].body
    assert "builtin version" not in recipes[0].body


def test_user_wins_over_builtin_when_no_project_override(
    isolated_dirs: tuple[Path, Path, Path],
) -> None:
    """No project override → user wins over built-in. Lets a user
    silently customise a bundled recipe."""
    project, user, builtin = isolated_dirs
    _write_recipe(
        user / ".config" / "code-scalpel" / "recipes",
        "python.md",
        "---\nname: python\n---\n\n# user version\n",
    )
    _write_recipe(builtin, "python.md", "---\nname: python\n---\n\n# builtin version\n")

    recipes = discover_recipes(project)
    assert "user version" in recipes[0].body


def test_format_recipes_block_drops_dir_specific_header() -> None:
    """Header no longer mentions `.code-scalpel/recipes/` because
    recipes can come from any of three dirs now. Generic label
    is the contract."""
    recipes = [Recipe(name="x", load="eager", body="# x\n")]
    block = format_recipes_block(recipes)
    assert "Loaded recipes:" in block
    assert ".code-scalpel" not in block

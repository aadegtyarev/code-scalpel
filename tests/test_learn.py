"""`/learn` generator — covers the path/filename hygiene, fence-stripping,
overwrite behaviour, and the empty-reply guard. Doesn't touch a real LLM —
the Runtime is built with a MockLLMAdapter so we can assert on the prompt
the model received and on the file we wrote."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.learn import _safe_filename, _strip_fences, learn
from code_scalpel.runtime import Runtime
from tests.mocks import MockLLMAdapter

_CONFIG = AppConfig(
    profiles={
        "local": ModelProfile(provider="lmstudio", model="local-model", temperature=0.1),
    },
    agent=AgentConfig(max_files=2, max_file_lines=50, enforce_read_before_show=False),
)


_VALID_RECIPE_BODY = """\
---
name: redis
load: lazy
file_patterns: ["*.py"]
allowed_commands: ["redis-cli"]
---

# redis
- bullet one
- bullet two
"""


def test_safe_filename_strips_punctuation_and_slashes() -> None:
    assert _safe_filename("redis") == "redis"
    assert _safe_filename("py-3.11") == "py-3.11"
    assert _safe_filename("foo/bar baz") == "foo_bar_baz"
    assert _safe_filename("../etc/passwd") == "etc_passwd"
    assert _safe_filename("") == "untitled"
    assert _safe_filename("@@@!!!") == "untitled"


def test_strip_fences_drops_outer_codefence() -> None:
    """Some models wrap the reply in ```markdown ... ``` despite being told
    not to. Strip the outer wrapper if it's there, leave inner fences alone."""
    wrapped = "```markdown\n" + _VALID_RECIPE_BODY.strip() + "\n```"
    assert _strip_fences(wrapped).startswith("---")
    assert "```" not in _strip_fences(wrapped).split("\n")[0]
    # No wrapper → return content untouched (trailing newline normalised).
    assert _strip_fences(_VALID_RECIPE_BODY).strip() == _VALID_RECIPE_BODY.strip()


@pytest.mark.asyncio
async def test_learn_writes_recipe_under_code_scalpel(tmp_path: Path) -> None:
    """Recipe MD lands at `.code-scalpel/recipes/<name>.md`. The model is
    fed a recipe-shaped prompt (must mention "recipe"); the saved file
    matches what the model emitted, with any outer codefence stripped."""
    llm = MockLLMAdapter([_VALID_RECIPE_BODY])
    runtime = Runtime(cwd=tmp_path, config=_CONFIG, llm=llm, with_memory=False)

    saved = await learn(runtime, "redis", kind="recipe")

    assert saved == tmp_path / ".code-scalpel" / "recipes" / "redis.md"
    assert saved.is_file()
    assert "name: redis" in saved.read_text()
    # The prompt routed through the recipe template (not the skill one).
    user_msg = next(m for m in llm.calls[0] if m["role"] == "user")["content"]
    assert "recipe" in user_msg.lower()


@pytest.mark.asyncio
async def test_learn_skill_lives_in_skills_dir(tmp_path: Path) -> None:
    """Skill files live under `.code-scalpel/skills/`, and the prompt uses
    the skill template (triggers + procedure, no allowed_commands)."""
    skill_body = """\
---
name: add_tests
triggers: ["add test", "тест"]
---

# add_tests
1. Identify happy path and edge case.
2. Write the test using mocks from tests/mocks.py.
3. Run pytest.
"""
    llm = MockLLMAdapter([skill_body])
    runtime = Runtime(cwd=tmp_path, config=_CONFIG, llm=llm, with_memory=False)

    saved = await learn(runtime, "add_tests", kind="skill")

    assert saved == tmp_path / ".code-scalpel" / "skills" / "add_tests.md"
    assert saved.read_text() == skill_body
    user_msg = next(m for m in llm.calls[0] if m["role"] == "user")["content"]
    assert "skill" in user_msg.lower()
    assert "triggers" in user_msg.lower()


@pytest.mark.asyncio
async def test_learn_overwrites_existing_file(tmp_path: Path) -> None:
    """Re-running `/learn foo` is the intended regenerate path — overwrite
    silently, no prompt. Otherwise a typo on iteration would orphan files."""
    target = tmp_path / ".code-scalpel" / "recipes" / "redis.md"
    target.parent.mkdir(parents=True)
    target.write_text("OLD CONTENT")

    new_body = _VALID_RECIPE_BODY.replace("bullet one", "fresh content")
    llm = MockLLMAdapter([new_body])
    runtime = Runtime(cwd=tmp_path, config=_CONFIG, llm=llm, with_memory=False)

    await learn(runtime, "redis", kind="recipe")
    assert "fresh content" in target.read_text()
    assert "OLD CONTENT" not in target.read_text()


@pytest.mark.asyncio
async def test_learn_rejects_reply_without_frontmatter(tmp_path: Path) -> None:
    """A reply with no `---` frontmatter fence isn't a recipe shape — refuse
    to write garbage to disk, surface the error to the caller."""
    llm = MockLLMAdapter(["sorry, I can't help with that today"])
    runtime = Runtime(cwd=tmp_path, config=_CONFIG, llm=llm, with_memory=False)

    with pytest.raises(RuntimeError, match="no usable"):
        await learn(runtime, "redis", kind="recipe")
    # And nothing landed on disk.
    assert not (tmp_path / ".code-scalpel" / "recipes" / "redis.md").exists()


@pytest.mark.asyncio
async def test_learn_sanitises_unsafe_names(tmp_path: Path) -> None:
    """A name with traversal characters must NOT escape `.code-scalpel/recipes/`.
    Stem gets sanitised; saved file ends up under the recipes dir regardless."""
    llm = MockLLMAdapter([_VALID_RECIPE_BODY])
    runtime = Runtime(cwd=tmp_path, config=_CONFIG, llm=llm, with_memory=False)

    saved = await learn(runtime, "../../etc/passwd", kind="recipe")
    # Saved under recipes/, name sanitised.
    assert saved.parent == tmp_path / ".code-scalpel" / "recipes"
    assert ".." not in saved.name
    assert saved.is_file()

"""`code-scalpel init` — interactive onboarding command.

Tests drive Typer's CliRunner with stdin input so we don't poke
the real terminal. The init flow doesn't use the Fork API: it
runs OUTSIDE the TUI (ChoiceCard isn't on screen yet), so a
typer.prompt wizard is the right tool.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from code_scalpel.cli import app


def test_init_writes_config_with_lmstudio_defaults(tmp_path: Path) -> None:
    """Pressing enter through every prompt should land a working
    lmstudio config — that's the «I have no idea, just give me
    defaults» path."""
    runner = CliRunner()
    # Six prompts: provider, model, base_url, sandbox.
    # Hitting return accepts the default each time.
    result = runner.invoke(app, ["init", "--path", str(tmp_path)], input="\n\n\n\n")

    assert result.exit_code == 0, result.stdout
    config = (tmp_path / ".code-scalpel" / "config.yaml").read_text()
    assert "provider: lmstudio" in config
    assert "qwen2.5-coder-14b-instruct" in config
    assert "base_url: http://localhost:1234/v1" in config
    assert "sandbox: auto" in config


def test_init_accepts_openrouter_choice(tmp_path: Path) -> None:
    """Switching provider changes the default model and drops the
    base_url prompt (only LM Studio needs it)."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--path", str(tmp_path)],
        # provider=openrouter, model default, sandbox default
        input="openrouter\n\n\n",
    )

    assert result.exit_code == 0, result.stdout
    config = (tmp_path / ".code-scalpel" / "config.yaml").read_text()
    assert "provider: openrouter" in config
    # OpenRouter doesn't get a base_url line in our template.
    assert "base_url:" not in config
    # And we leave a hint about the API key env var.
    assert "OPENROUTER_API_KEY" in config


def test_init_refuses_unknown_provider(tmp_path: Path) -> None:
    """Unknown provider → loop until valid. Three retries with the
    same junk would normally hang the test; we feed exactly one
    junk + the correct value."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--path", str(tmp_path)],
        input="cohere\nlmstudio\n\n\n\n",
    )

    assert result.exit_code == 0, result.stdout
    assert "pick one of" in result.stdout
    config = (tmp_path / ".code-scalpel" / "config.yaml").read_text()
    assert "provider: lmstudio" in config


def test_init_prompts_before_overwriting_existing(tmp_path: Path) -> None:
    """User shouldn't be able to wipe a hand-edited config by
    accident. Default answer is `N`."""
    config_dir = tmp_path / ".code-scalpel"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("# hand-tuned, do not lose me\n")

    runner = CliRunner()
    # User says No (default).
    result = runner.invoke(app, ["init", "--path", str(tmp_path)], input="\n")

    assert result.exit_code == 1
    # File is unchanged.
    assert (config_dir / "config.yaml").read_text() == "# hand-tuned, do not lose me\n"


def test_init_force_bypasses_confirm(tmp_path: Path) -> None:
    """`--force` is the explicit «I know what I'm doing» knob."""
    config_dir = tmp_path / ".code-scalpel"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("# stale\n")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--path", str(tmp_path), "--force"],
        input="\n\n\n\n",
    )

    assert result.exit_code == 0, result.stdout
    config = (config_dir / "config.yaml").read_text()
    assert "stale" not in config
    assert "provider:" in config


def test_init_creates_gitignore_when_absent(tmp_path: Path) -> None:
    """First-time setup adds `.code-scalpel/` to .gitignore so the
    new directory doesn't end up in the repo."""
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--path", str(tmp_path)], input="\n\n\n\n")

    assert result.exit_code == 0, result.stdout
    gitignore = (tmp_path / ".gitignore").read_text()
    assert ".code-scalpel/" in gitignore


def test_init_leaves_existing_gitignore_alone(tmp_path: Path) -> None:
    """If a .gitignore is already there, don't touch it — the user
    might have a polished version we'd clobber."""
    (tmp_path / ".gitignore").write_text("custom_pattern\n")

    runner = CliRunner()
    result = runner.invoke(app, ["init", "--path", str(tmp_path)], input="\n\n\n\n")

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / ".gitignore").read_text() == "custom_pattern\n"

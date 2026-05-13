from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from code_scalpel import __version__
from code_scalpel.config import load_config

# `invoke_without_command=True` lets `code-scalpel` keep launching the TUI
# directly (no subcommand) while `code-scalpel init …` and any future
# subcommands route through their own handlers. The callback fires for
# every invocation; we only fall into the TUI path when no subcommand was
# requested.
app = typer.Typer(
    name="code-scalpel",
    help="TUI coding agent for weak local LLMs.",
    no_args_is_help=False,
    invoke_without_command=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"code-scalpel {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    path_opt: Annotated[
        Path | None,
        typer.Option(
            "--path",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Working directory (default: current dir)",
            show_default=False,
        ),
    ] = None,
    version: Annotated[  # noqa: ARG001 — callback consumes the flag
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
) -> None:
    """Launch the TUI in the given directory when no subcommand is given.

    The legacy `code-scalpel <path>` positional shortcut is gone — Typer
    can't tell `init` (a subcommand) apart from `init` (a directory
    name) when there are subcommands. Use `--path <dir>` instead.
    """
    if ctx.invoked_subcommand is not None:
        return
    from code_scalpel.tui.app import ScalpelApp

    cwd = (path_opt or Path(".")).resolve()
    config = load_config()
    scalpel = ScalpelApp(config=config, cwd=cwd)
    scalpel.run()
    summary = getattr(scalpel, "_exit_summary", None)
    if summary:
        typer.echo(summary)


_PROVIDERS = ("lmstudio", "openrouter", "openai")
_SANDBOX = ("auto", "on", "off")


@app.command(help="Interactive onboarding — creates .code-scalpel/config.yaml.")
def init(
    path: Annotated[
        Path | None,
        typer.Option(
            "--path",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Target project directory (default: current dir).",
            show_default=False,
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite existing config.yaml without asking.",
        ),
    ] = False,
) -> None:
    """Walk the user through provider / model / sandbox choices, then
    write the resulting `.code-scalpel/config.yaml` and a starter
    `.gitignore`.

    Same shape as a Fork API session (a list of choices delegated to
    the human), but Typer's `prompt` flow is the right call here:
    init runs OUTSIDE the TUI, so ChoiceCard isn't on screen yet.
    """
    cwd = (path or Path(".")).resolve()
    target_dir = cwd / ".code-scalpel"
    target_dir.mkdir(parents=True, exist_ok=True)
    config_path = target_dir / "config.yaml"

    if (
        config_path.exists()
        and not force
        and not typer.confirm(f"{config_path} already exists. Overwrite?", default=False)
    ):
        typer.echo("Aborted — existing config untouched.")
        raise typer.Exit(code=1)

    typer.echo(f"Initialising code-scalpel in {cwd}\n")

    provider = _prompt_choice(
        "Which LLM provider do you use?",
        _PROVIDERS,
        default="lmstudio",
    )
    model_default = _default_model_for(provider)
    model = typer.prompt("Model name", default=model_default)
    base_url = _default_base_url(provider)
    if provider == "lmstudio" and base_url:
        base_url = typer.prompt("LM Studio base URL", default=base_url)

    sandbox = _prompt_choice(
        "Sandbox shell_exec via bwrap?",
        _SANDBOX,
        default="auto",
    )

    config_yaml = _render_config(
        provider=provider,
        model=model,
        base_url=base_url,
        sandbox=sandbox,
    )
    config_path.write_text(config_yaml)
    typer.echo(f"\nWrote {config_path}")

    gitignore = cwd / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(".code-scalpel/\n")
        typer.echo(f"Wrote {gitignore} (added .code-scalpel/ entry)")

    typer.echo("\nNext: run `code-scalpel` in this directory to launch the TUI.")


def _prompt_choice(question: str, choices: tuple[str, ...], *, default: str) -> str:
    """Tiny choice-list prompt — Typer's stock prompt accepts free text;
    we want a closed set. Loops until the user enters one of the
    options."""
    while True:
        # typer.prompt is typed Any in older typer versions — pin to str.
        value: str = str(
            typer.prompt(f"{question} [{'/'.join(choices)}]", default=default)
        )
        if value in choices:
            return value
        typer.echo(f"  → pick one of: {', '.join(choices)}")


def _default_model_for(provider: str) -> str:
    if provider == "lmstudio":
        return "qwen2.5-coder-14b-instruct"
    if provider == "openrouter":
        return "anthropic/claude-sonnet-4"
    if provider == "openai":
        return "gpt-4o-mini"
    return ""


def _default_base_url(provider: str) -> str:
    if provider == "lmstudio":
        return "http://localhost:1234/v1"
    return ""


def _render_config(*, provider: str, model: str, base_url: str, sandbox: str) -> str:
    """Build a minimal config.yaml. Comments explain the next steps so
    the user can grow it without reading docs."""
    lines = [
        "# code-scalpel config — generated by `code-scalpel init`.",
        "# Tweak freely; the agent reloads on the next launch.",
        "",
        "agent:",
        f"  sandbox: {sandbox}",
        "",
        "profiles:",
        "  default:",
        f"    provider: {provider}",
        f"    model: {model}",
    ]
    if base_url:
        lines.append(f"    base_url: {base_url}")
    lines.append("")
    if provider in {"openrouter", "openai"}:
        lines.extend(
            [
                "# Provider key — set the env var instead of writing it here.",
                f"#   {provider.upper()}_API_KEY=<your key>",
            ]
        )
    return "\n".join(lines) + "\n"

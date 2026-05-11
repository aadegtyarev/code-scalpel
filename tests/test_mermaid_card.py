"""Widget tests for `MermaidCard` — the inline diagram surface.

Tests do NOT call the real mmdc binary; they monkeypatch `shutil.which`
and `subprocess.run` so the three render tiers can be exercised in
isolation without depending on the dev box having the Node CLI installed.
"""

from __future__ import annotations

from typing import Any

import pytest
from rich.console import Console
from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.widgets import Static

from code_scalpel.tui.widgets import mermaid_card as mc_module
from code_scalpel.tui.widgets.mermaid_card import MermaidCard

_SOURCE = "flowchart TD\n    A --> B\n"


class _Harness(App[None]):
    def __init__(self, card: MermaidCard) -> None:
        super().__init__()
        self._card = card

    def compose(self) -> ComposeResult:
        yield self._card


def _all_text(card: MermaidCard) -> str:
    """Concatenate plain-text render of every Static inside the card.

    Textual wraps Static contents into a `RichVisual`; we have to unwrap
    via `_renderable` to get the underlying Syntax/Pixels/markup string,
    then drop it through a Rich Console with color disabled so what we
    assert against is plain user-visible text.
    """
    console = Console(file=None, record=True, width=120, color_system=None)
    for s in card.query(Static):
        try:
            visual = s.visual
            inner = getattr(visual, "_renderable", visual)
        except Exception:
            continue
        if isinstance(inner, Syntax):
            # Syntax keeps the source as `.code` — render it directly so
            # the assertion can match the mermaid block by substring.
            console.print(inner.code)
            continue
        try:
            console.print(inner)
        except Exception:
            console.print(repr(inner))
    return console.export_text()


@pytest.mark.asyncio
async def test_card_mounts_with_raw_source_when_mmdc_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No mmdc on PATH → tier-3 fallback: install hint + raw source. Card
    must NOT crash and must contain the mermaid source verbatim."""
    monkeypatch.setattr(mc_module.shutil, "which", lambda _name: None)
    card = MermaidCard(_SOURCE)
    app = _Harness(card)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        text = _all_text(card)
        # Hint advertising the upgrade path is present.
        assert "Install" in text
        # Source is rendered (via Syntax) — substring check on a token
        # that's unique to mermaid flowcharts.
        assert "flowchart TD" in text


@pytest.mark.asyncio
async def test_card_shows_error_when_mmdc_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mmdc available but exits non-zero (e.g. invalid mermaid syntax) →
    card replaces the install hint with a compact error line, raw source
    stays visible underneath."""
    monkeypatch.setattr(mc_module.shutil, "which", lambda _name: "/fake/mmdc")

    class _FakeProc:
        returncode = 1
        stderr = b"Parse error on line 1: unexpected token"
        stdout = b""

    def _fake_run(*_args: Any, **_kwargs: Any) -> _FakeProc:
        return _FakeProc()

    monkeypatch.setattr(mc_module.subprocess, "run", _fake_run)

    card = MermaidCard("not really mermaid")
    app = _Harness(card)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        # Give the on_mount worker a beat to fail through.
        await pilot.pause(0.2)
        text = _all_text(card)
        assert "mmdc error" in text
        # Source stays visible — user can still copy/paste and fix.
        assert "not really mermaid" in text


@pytest.mark.asyncio
async def test_card_with_valid_source_renders_without_install_hint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """mmdc + rich-pixels both present, mmdc "succeeds" → install hint
    must disappear. We don't actually shell out: we fake mmdc to write
    a tiny PNG and let the real Pixels render path execute on it."""
    monkeypatch.setattr(mc_module.shutil, "which", lambda _name: "/fake/mmdc")

    # Fake mmdc: write a 2×2 PNG to the -o path, return 0.
    png_path_holder: dict[str, str] = {}

    def _fake_run(args: Any, **_kwargs: Any) -> Any:
        # Args: ["mmdc", "-i", "-", "-o", <path>, ...]
        out_idx = args.index("-o") + 1
        out_path = args[out_idx]
        try:
            from PIL import Image

            Image.new("RGB", (2, 2), color="black").save(out_path)
        except Exception:
            # Без Pillow картинку не сделать — пусть тест зафейлится явно.
            raise

        class _OK:
            returncode = 0
            stderr = b""
            stdout = b""

        png_path_holder["path"] = out_path
        return _OK()

    monkeypatch.setattr(mc_module.subprocess, "run", _fake_run)

    if mc_module._Pixels is None:
        pytest.skip("rich-pixels not installed; tier-1 path can't be exercised")

    card = MermaidCard(_SOURCE)
    app = _Harness(card)
    async with app.run_test(headless=True, size=(80, 24)) as pilot:
        # Worker needs a moment to: run fake mmdc + decode PNG + swap body.
        await pilot.pause(0.3)
        text = _all_text(card)
        # Successful render path removed the install hint.
        assert "Install" not in text
        assert "mmdc error" not in text

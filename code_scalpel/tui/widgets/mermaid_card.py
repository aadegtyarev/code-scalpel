"""Inline card that renders a ```mermaid ... ``` block from the model's reply.

Three-tier fallback:

1. `mmdc` (Mermaid CLI) on PATH AND `rich-pixels` importable → render to
   PNG and draw via Unicode half-blocks inside a Static.
2. mmdc available but invocation fails (bad mermaid syntax, etc.) →
   show the raw source plus a one-line error hint.
3. Neither dep available → show the raw source plus an install hint.

Никакой malformed mermaid (или сетевой пакет, или капризы npm-обёртки)
не должен валить TUI. Все исключения ловим, fallback всегда — текст
блока в Static.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from rich.markup import escape
from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Collapsible, Static

# rich-pixels — optional. Если пакет не установлен, мы остаёмся в
# текстовом фоллбэке. Импорт под try/except, чтобы отсутствие пакета
# не ломало tui-модуль на старте.
try:
    from rich_pixels import Pixels as _Pixels
except ImportError:  # pragma: no cover - exercised by env without rich-pixels
    _Pixels = None  # type: ignore[assignment,misc]


_INSTALL_HINT = (
    "[dim]Install [b]mmdc[/b] (npm i -g @mermaid-js/mermaid-cli) + "
    "[b]rich-pixels[/b] to render diagrams inline.[/]"
)


class MermaidCard(Widget):
    """Inline card showing one mermaid block: rendered PNG or raw source."""

    DEFAULT_CSS = """
    MermaidCard {
        height: auto;
        background: #0f0f0f;
        margin: 1 0 0 0;
        padding: 0;
    }
    MermaidCard Collapsible {
        background: #0f0f0f;
        border: none;
        padding: 0;
        margin: 0;
    }
    MermaidCard Collapsible > Contents {
        background: #161616;
        padding: 0 1;
        color: #c0c0c0;
    }
    MermaidCard CollapsibleTitle {
        background: #0f0f0f;
        padding: 0;
        color: #c0c0c0;
    }
    MermaidCard Static.mermaid-body {
        height: auto;
        background: #161616;
        color: #c0c0c0;
    }
    MermaidCard Static.mermaid-hint {
        height: auto;
        background: #161616;
        color: #707070;
    }
    """

    def __init__(self, source: str) -> None:
        super().__init__()
        self._source = source
        # Состояние, обновляемое в on_mount→worker. compose() рендерит
        # placeholder; настоящий контент вставляется в _swap_body после
        # того, как воркер закончил рендер.
        self._rendered: Any | None = None
        self._error: str | None = None

    # ── compose ───────────────────────────────────────────────────────────

    def _title(self) -> str:
        # Чистый литерал — markup=True безопасен.
        return "[bold]🗺  Mermaid diagram[/bold]"

    def compose(self) -> ComposeResult:
        # collapsed=False — диаграмма это main artefact ответа, как PlanCard.
        with Collapsible(title=self._title(), collapsed=False):
            # Placeholder: hint + raw source. Воркер потом, если повезло,
            # подменит на отрендеренный Pixels.
            yield Static(_INSTALL_HINT, classes="mermaid-hint")
            yield Static(
                Syntax(self._source, "yaml", theme="monokai", background_color="default"),
                classes="mermaid-body",
                id="mermaid-source",
            )

    def on_mount(self) -> None:
        # Render off the event loop. CLI вызов + Pillow decoding — оба
        # могут стоить десятки-сотни мс на крупной диаграмме, нельзя
        # фризить TUI.
        self.run_worker(self._render_mermaid(), exclusive=False)

    # ── render pipeline ───────────────────────────────────────────────────

    async def _render_mermaid(self) -> None:
        """Attempt mmdc → PNG → rich-pixels. Mutates `self._rendered` /
        `self._error` and calls `_swap_body`. Любая ошибка — silent
        fallback на текст; никакой crash."""
        if shutil.which("mmdc") is None:
            return  # tier 3: hint + raw source, уже отрисовано в compose
        try:
            png_path = await asyncio.to_thread(_mmdc_render, self._source)
        except _MmdcError as e:
            self._error = str(e)
            await self._swap_body()
            return
        except Exception as e:  # pragma: no cover - defensive
            self._error = f"mmdc failed: {e}"
            await self._swap_body()
            return
        if _Pixels is None:
            # mmdc сработал, но рендерить нечем. Hint оставляем (только
            # rich-pixels не хватает) — он уже на месте.
            return
        try:
            pixels = await asyncio.to_thread(_Pixels.from_image_path, png_path)
        except Exception as e:  # pragma: no cover - defensive
            self._error = f"image render failed: {e}"
            await self._swap_body()
            return
        finally:
            # Tempfile — наша зона ответственности, чистим вне зависимости
            # от исхода Pixels-конвертации.
            with contextlib.suppress(Exception):
                Path(png_path).unlink(missing_ok=True)
        self._rendered = pixels
        await self._swap_body()

    async def _swap_body(self) -> None:
        """Replace the placeholder content based on render outcome."""
        try:
            hint = self.query_one(".mermaid-hint", Static)
            body = self.query_one("#mermaid-source", Static)
        except Exception:
            return
        if self._rendered is not None:
            # Успех: убираем hint, заменяем тело на picture.
            try:
                await hint.remove()
                body.update(self._rendered)
            except Exception:
                pass
            return
        if self._error is not None:
            # mmdc упал — оставим raw source, заменим hint на компактную
            # строку ошибки (escape — текст может содержать `[`).
            with contextlib.suppress(Exception):
                hint.update(f"[#bf6060]mmdc error:[/] {escape(self._error)}")


# ── mmdc shell-out ────────────────────────────────────────────────────────


class _MmdcError(RuntimeError):
    """Raised when mmdc returns non-zero. Carries trimmed stderr."""


def _mmdc_render(source: str) -> str:
    """Run mmdc with *source* on stdin, return path to a PNG tempfile.

    Caller owns the file (must unlink). stdin protocol: pipe mermaid
    source, `-i -` tells mmdc to read it. `-o` is the output path; we
    pre-allocate a NamedTemporaryFile so mmdc can overwrite it.
    """
    # delete=False — мы вернём путь, удаление в caller.
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        out_path = tmp.name
    proc = subprocess.run(
        ["mmdc", "-i", "-", "-o", out_path, "-b", "transparent"],
        input=source.encode("utf-8"),
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        # Сначала чистим за собой, потом кидаем — иначе мусор в /tmp.
        with contextlib.suppress(Exception):
            Path(out_path).unlink(missing_ok=True)
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        # Cap длины — диагностика, не лог.
        if len(err) > 400:
            err = err[:400] + "…"
        raise _MmdcError(err or "mmdc returned non-zero exit code")
    return out_path


__all__ = ["MermaidCard"]

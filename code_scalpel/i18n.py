"""Localisation for the TUI surface — `t(key)` + ru/en yaml catalogs.

What's translated: status-bar text, slash-command descriptions, error
messages, mode labels. What stays English no matter what: CLI flags,
slash-command names (`/learn`, `/map`, …), file paths, hotkey
captions (`ctrl+q`, `ctrl+t`), tool names (`project_map`, `read_file`).
The prompts the model receives also stay English — qwen-coder-14b
performs measurably better on English prompts, that's a model fact,
not a UX choice.

Locale resolution order on first `t()` call:
  1. explicit `set_locale(...)` from caller (config knob)
  2. `LC_ALL` / `LC_MESSAGES` / `LANG` env vars (POSIX standard)
  3. fallback to "en"

Missing keys return the key string verbatim — that way a typo is
visible in the UI ("error.no_llm" appearing on screen) instead of
silently rendering as empty.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_LOCALE_DIR = Path(__file__).parent / "locale"
_DEFAULT_LOCALE = "en"
_SUPPORTED = ("en", "ru")

# Module-global override — set once at app startup from config.
# `None` means "fall through to env detection on every t() call".
_forced_locale: str | None = None


def set_locale(locale: str | None) -> None:
    """Pin the UI language for this process. Pass `None` to fall back
    to env autodetect. Unknown locale → default (`en`)."""
    global _forced_locale
    if locale is None:
        _forced_locale = None
        return
    _forced_locale = locale if locale in _SUPPORTED else _DEFAULT_LOCALE
    # Bust the catalog cache: `t()` should re-read for the new locale
    # without a process restart (`/lang ru` style toggles).
    _catalog.cache_clear()


def _detect_from_env() -> str:
    """Read POSIX locale env vars and return our short tag (`ru`/`en`).
    LC_ALL beats LC_MESSAGES beats LANG, matching glibc's resolution
    order; anything not Russian falls back to default."""
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if val:
            tag = val.split(".", 1)[0].split("_", 1)[0].lower()
            if tag in _SUPPORTED:
                return tag
            break  # first set var wins, even if it's unsupported
    return _DEFAULT_LOCALE


def _current_locale() -> str:
    return _forced_locale or _detect_from_env()


@lru_cache(maxsize=8)
def _catalog(locale: str) -> dict[str, str]:
    """Load and flatten the yaml catalog for `locale`. Cached because
    yaml.safe_load is non-trivial and we hit `t()` on every render."""
    path = _LOCALE_DIR / f"{locale}.yaml"
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return _flatten(raw)


def _flatten(tree: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Turn nested yaml dicts into flat dot-separated keys.

    `tone.no_llm: "..."` in the file becomes `t("tone.no_llm")` in
    code. Nested grouping is a writability convenience for the
    catalog file — at lookup time we just want a flat map.
    """
    out: dict[str, str] = {}
    for key, value in tree.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, full))
        elif isinstance(value, str):
            out[full] = value
    return out


def t(key: str, **fmt: object) -> str:
    """Look up `key` in the current locale; fall back to `en`; then
    fall back to the key itself. `**fmt` is passed through `str.format`
    so callers can do `t("status.thinking", elapsed=2.4)` against a
    catalog entry of `"thinking… ({elapsed:.1f}s)"`.

    Format errors (missing field, bad spec) return the raw template —
    a half-formatted UI string is more useful than a `KeyError` from
    a status-bar render path."""
    cat = _catalog(_current_locale())
    template = cat.get(key)
    if template is None and _current_locale() != _DEFAULT_LOCALE:
        # Locale-specific catalog might omit a key the en one defines;
        # fall through rather than show the dotted key on screen.
        template = _catalog(_DEFAULT_LOCALE).get(key)
    if template is None:
        return key
    if not fmt:
        return template
    try:
        return template.format(**fmt)
    except (KeyError, IndexError, ValueError):
        return template

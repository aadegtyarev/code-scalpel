"""i18n — t() lookup, locale resolution, missing-key fallback.

Tests don't depend on real environment vars (they monkey-patch).
Catalogs are loaded from the real yaml files under
`code_scalpel/locale/` — that's the contract we want to pin.
"""

from __future__ import annotations

import pytest

from code_scalpel import i18n


@pytest.fixture(autouse=True)
def _reset_locale_state() -> None:
    """Make every test start clean: no forced locale, empty cache.
    Otherwise yield-order between tests would flake the catalog state."""
    i18n.set_locale(None)
    i18n._catalog.cache_clear()


def test_t_returns_english_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no forced locale and no Russian LANG, t() returns the English
    catalog entry."""
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    i18n._catalog.cache_clear()  # picked up new env

    assert i18n.t("status.idle") == "● idle"


def test_t_picks_russian_when_lang_is_ru(monkeypatch: pytest.MonkeyPatch) -> None:
    """`LANG=ru_RU.UTF-8` flips the catalog. Verifies env autodetect
    works end-to-end, not just via the explicit `set_locale` knob."""
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    i18n._catalog.cache_clear()

    assert i18n.t("status.idle") == "● готов"


def test_set_locale_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Config-set locale beats environment detection — the user wants
    Russian UI on an English-locale machine, that should work."""
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    i18n.set_locale("ru")

    assert i18n.t("status.idle") == "● готов"


def test_set_locale_none_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Passing `None` clears the override and resumes env-driven detection."""
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    i18n.set_locale("en")
    assert i18n.t("status.idle") == "● idle"
    i18n.set_locale(None)
    i18n._catalog.cache_clear()
    assert i18n.t("status.idle") == "● готов"


def test_t_missing_key_returns_key_verbatim() -> None:
    """A typo in a callsite (`status.nope`) shows up on screen as
    'status.nope' — visible failure beats silent empty string."""
    assert i18n.t("status.nope_definitely_missing") == "status.nope_definitely_missing"


def test_t_format_args() -> None:
    """Catalog entries with `{placeholders}` get .format()'d. Both
    English and Russian carry the same arg shape."""
    i18n.set_locale("en")
    assert i18n.t("error.config", message="bad yaml") == "Config error: bad yaml"
    i18n.set_locale("ru")
    assert i18n.t("error.config", message="bad yaml") == "Ошибка конфига: bad yaml"


def test_t_format_args_missing_field_returns_template() -> None:
    """Caller forgot to pass a kw — return the raw template rather than
    crash the render path. A half-formatted string is still useful."""
    i18n.set_locale("en")
    # error.config wants {message} but we don't pass it
    result = i18n.t("error.config")
    assert "Config error:" in result
    assert "{message}" in result  # template returned as-is


def test_ru_catalog_falls_back_to_en_for_missing_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If we add a key to en.yaml but forget to translate it, the
    Russian view should fall through to English rather than show the
    dotted key string. Simulate the gap by stubbing the ru catalog
    to a single entry — every other key must fall through to en."""

    def fake_catalog(locale: str) -> dict[str, str]:
        if locale == "ru":
            return {"tmp.only_ru": "только русский"}
        return {"status.idle": "● idle", "tmp.only_en": "English fallback"}

    # Preserve the .cache_clear attribute that `set_locale` will try to
    # call after we swap the function out.
    fake_catalog.cache_clear = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setattr(i18n, "_catalog", fake_catalog)
    i18n.set_locale("ru")

    # Defined in ru → ru wins.
    assert i18n.t("tmp.only_ru") == "только русский"
    # Defined only in en → ru lookup falls through.
    assert i18n.t("status.idle") == "● idle"
    assert i18n.t("tmp.only_en") == "English fallback"


def test_unsupported_locale_falls_back_to_default() -> None:
    """`set_locale("klingon")` shouldn't break the world — coerce to
    the default. We log nothing; the catalog miss is the signal."""
    i18n.set_locale("klingon")
    assert i18n.t("status.idle") == "● idle"

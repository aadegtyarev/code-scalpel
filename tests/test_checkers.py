"""Тесты механических чекеров probe-сценариев.

Чистую логику (счёт критериев, gating, структурные детекторы,
реестр, сериализация) гоняем быстро и offline. Поведенческий путь
`_install_and_test` (эфемерный venv + pytest) — opt-in тест,
включается переменной `PROBE_SLOW_TESTS=1`: он медленный и тянет
pytest из сети, поэтому не должен блокировать `pytest -x`."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from scripts.probes_v2.checkers import (
    CheckResult,
    Criterion,
    check_notes_cli,
    has_checker,
    run_checks,
)


def _write(tree: Path, rel: str, body: str) -> None:
    path = tree / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def _working_notes_tree(tree: Path) -> None:
    """Структурно-валидный notes_cli: пакет, 4 команды, json-storage,
    тесты. Без поведенческого прогона (run_tests=False)."""
    _write(
        tree,
        "notes/cli.py",
        """
        import json
        from pathlib import Path

        STORE = Path("notes.json")

        def _load():
            return json.load(STORE.open()) if STORE.exists() else []

        def add(text):
            data = _load()
            data.append(text)
            json.dump(data, STORE.open("w"))

        def list():  # noqa: A001
            return _load()

        def search(q):
            return [n for n in _load() if q in n]

        def delete(i):
            data = _load()
            del data[i]
            json.dump(data, STORE.open("w"))

        def main():
            import argparse
            p = argparse.ArgumentParser()
            sub = p.add_subparsers(dest="cmd")
            a = sub.add_parser("add"); a.add_argument("text")
            sub.add_parser("list")
            s = sub.add_parser("search"); s.add_argument("q")
            d = sub.add_parser("delete"); d.add_argument("i", type=int)
            args = p.parse_args()
            if args.cmd == "add":
                add(args.text)
            elif args.cmd == "list":
                for n in list():
                    print(n)
            elif args.cmd == "search":
                for n in search(args.q):
                    print(n)
            elif args.cmd == "delete":
                delete(args.i)

        if __name__ == "__main__":
            main()
        """,
    )
    _write(tree, "notes/__init__.py", "")
    _write(tree, "tests/__init__.py", "")
    _write(tree, "tests/test_cli.py", "def test_smoke():\n    assert True\n")
    _write(tree, "README.md", "# notes\n\nA tiny notes CLI: add / list / search / delete.\n")


# ── CheckResult: математика и gating ─────────────────────────────


def test_pass_score_and_max_count_all_criteria() -> None:
    res = CheckResult(
        criteria={
            "a": Criterion(True, ""),
            "b": Criterion(False, ""),
            "c": Criterion(True, ""),
        },
        gating=("a",),
    )
    assert res.pass_score == 2
    assert res.pass_max == 3


def test_solved_requires_all_gating_criteria() -> None:
    crits = {"a": Criterion(True, ""), "b": Criterion(False, "")}
    assert CheckResult(crits, gating=("a",)).solved is True
    assert CheckResult(crits, gating=("a", "b")).solved is False


def test_empty_gating_is_not_solved() -> None:
    """Сценарий без gating-критериев не может быть «решён» — иначе
    отсутствие проверок читалось бы как успех."""
    res = CheckResult({"a": Criterion(True, "")}, gating=())
    assert res.solved is False


def test_to_verdict_shape() -> None:
    res = CheckResult({"a": Criterion(True, "ok")}, gating=("a",))
    v = res.to_verdict()
    assert v["pass_score"] == 1
    assert v["pass_max"] == 1
    assert v["mechanical_solved"] is True
    assert v["criteria"]["a"] == {"passed": True, "detail": "ok"}


# ── структурные детекторы (быстро, run_tests=False) ──────────────


def test_structural_pass_on_working_tree(tmp_path: Path) -> None:
    _working_notes_tree(tmp_path)
    res = check_notes_cli(tmp_path, run_tests=False)
    assert res.criteria["package"].passed
    assert res.criteria["four_commands"].passed
    assert res.criteria["json_storage"].passed
    assert res.criteria["tests_present"].passed
    assert res.criteria["docs"].passed
    # tests_pass отсутствует — поведение не гоняли
    assert "tests_pass" not in res.criteria


def test_missing_command_fails_four_commands(tmp_path: Path) -> None:
    _write(tmp_path, "app.py", "def add(): ...\ndef list(): ...\ndef search(): ...\n")
    res = check_notes_cli(tmp_path, run_tests=False)
    assert not res.criteria["four_commands"].passed
    assert "delete" in res.criteria["four_commands"].detail


def test_four_commands_detects_snake_case(tmp_path: Path) -> None:
    """`def add_note()` и т.п. должны засчитываться: голова snake_case
    — это команда. Регрессия — `\\bword\\b` промахивался по `add_note`."""
    _write(
        tmp_path,
        "notes.py",
        "def add_note(): ...\ndef list_notes(): ...\n"
        "def search_notes(): ...\ndef delete_note(): ...\n",
    )
    res = check_notes_cli(tmp_path, run_tests=False)
    assert res.criteria["four_commands"].passed, res.criteria["four_commands"].detail


def test_four_commands_no_false_positive_on_substrings(tmp_path: Path) -> None:
    """`address`/`listing`/`research`/`deleted` не должны засчитываться
    как команды add/list/search/delete."""
    _write(tmp_path, "app.py", "address = 1\nlisting = 2\nresearch = 3\ndeleted = 4\n")
    res = check_notes_cli(tmp_path, run_tests=False)
    assert not res.criteria["four_commands"].passed


def test_json_storage_needs_both_api_and_path(tmp_path: Path) -> None:
    # только json.dump, без .json-пути → не зачёт
    _write(tmp_path, "app.py", "import json\njson.dump({}, open('x','w'))\n")
    res = check_notes_cli(tmp_path, run_tests=False)
    assert not res.criteria["json_storage"].passed


def test_package_detector_ignores_tests_and_empty(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_x.py", "def test(): assert True\n")
    _write(tmp_path, "empty.py", "")
    res = check_notes_cli(tmp_path, run_tests=False)
    # только тест-файл и пустой модуль → нет пакетного кода
    assert not res.criteria["package"].passed


def test_docs_readme_detected(tmp_path: Path) -> None:
    _working_notes_tree(tmp_path)  # уже содержит README.md
    res = check_notes_cli(tmp_path, run_tests=False)
    assert res.criteria["docs"].passed


def test_docs_docstring_fallback(tmp_path: Path) -> None:
    """Нет README, но есть докстринг → docs зачтён по фолбэку."""
    _write(tmp_path, "app.py", '"""Notes CLI."""\n\ndef add(): ...\n')
    res = check_notes_cli(tmp_path, run_tests=False)
    assert res.criteria["docs"].passed
    assert "докстринг" in res.criteria["docs"].detail


def test_docs_absent_fails(tmp_path: Path) -> None:
    """Ни README, ни докстрингов → docs не зачтён, итог не solved."""
    _write(tmp_path, "app.py", "def add(): ...\ndef delete(): ...\n")
    res = check_notes_cli(tmp_path, run_tests=False)
    assert not res.criteria["docs"].passed


def test_structural_only_is_not_solved(tmp_path: Path) -> None:
    """Без поведенческого прогона solved=False даже на идеальной
    структуре — honest «похоже, но не проверено»."""
    _working_notes_tree(tmp_path)
    res = check_notes_cli(tmp_path, run_tests=False)
    assert res.solved is False


# ── acceptance: CLI реально запускается ──────────────────────────


def test_acceptance_fails_without_cli_entry(tmp_path: Path) -> None:
    """Функции add/list/… есть, но нет __main__/argparse → не CLI.
    Ловит ложный solved (acbe16d: `python notes.py add x` ничего не
    делал, а solved был True по тестам модели)."""
    from scripts.probes_v2.checkers import check_cli_acceptance

    _write(
        tmp_path,
        "notes.py",
        "import json\ndef add(t): json.dump([t], open('s.json','w'))\ndef list(): ...\n",
    )
    res = check_cli_acceptance(tmp_path)
    assert not res.passed
    assert "точк" in res.detail.lower()


def test_acceptance_passes_on_working_cli(tmp_path: Path) -> None:
    """Реальный argparse-CLI: add→list через `python notes.py` → pass."""
    from scripts.probes_v2.checkers import check_cli_acceptance

    _write(
        tmp_path,
        "notes.py",
        "import sys, json, argparse\n"
        "STORE='storage.json'\n"
        "def _load():\n"
        "    try: return json.load(open(STORE))\n"
        "    except FileNotFoundError: return []\n"
        "def main():\n"
        "    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd')\n"
        "    a=sub.add_parser('add'); a.add_argument('text')\n"
        "    sub.add_parser('list')\n"
        "    args=p.parse_args(); n=_load()\n"
        "    if args.cmd=='add': n.append(args.text); json.dump(n, open(STORE,'w'))\n"
        "    elif args.cmd=='list':\n"
        "        [print(x) for x in n]\n"
        "if __name__=='__main__': main()\n",
    )
    res = check_cli_acceptance(tmp_path)
    assert res.passed, res.detail


def test_acceptance_is_gating(tmp_path: Path) -> None:
    """acceptance входит в gating: рабочий код+тесты без CLI ≠ solved."""
    res = check_notes_cli(tmp_path, run_tests=False)
    assert "acceptance" in res.gating


# ── реестр ───────────────────────────────────────────────────────


def test_registry_known_and_unknown() -> None:
    assert has_checker("notes_cli")
    assert not has_checker("nope_scenario")


def test_run_checks_unknown_scenario_returns_none(tmp_path: Path) -> None:
    assert run_checks("nope_scenario", tmp_path) is None


def test_run_checks_known_scenario_returns_result(tmp_path: Path) -> None:
    _working_notes_tree(tmp_path)
    res = run_checks("notes_cli", tmp_path, run_tests=False)
    assert res is not None
    assert res.pass_max == 5  # package, four_commands, json_storage, tests_present, docs


# ── поведенческий путь (opt-in: venv + pytest) ───────────────────


@pytest.mark.skipif(
    os.environ.get("PROBE_SLOW_TESTS") != "1",
    reason="ставит эфемерный venv + pytest; включается PROBE_SLOW_TESTS=1",
)
def test_install_and_test_green_on_stdlib_project(tmp_path: Path) -> None:
    """Stdlib-only проект с зелёным тестом → tests_pass и solved."""
    _write(
        tmp_path,
        "pyproject.toml",
        """
        [build-system]
        requires = ["hatchling"]
        build-backend = "hatchling.build"

        [project]
        name = "notes"
        version = "0.0.0"
        requires-python = ">=3.11"
        dependencies = []

        [project.optional-dependencies]
        dev = ["pytest>=8"]
        """,
    )
    _working_notes_tree(tmp_path)
    res = check_notes_cli(tmp_path, run_tests=True)
    assert res.criteria["tests_pass"].passed, res.criteria["tests_pass"].detail
    assert res.solved is True


@pytest.mark.skipif(
    os.environ.get("PROBE_SLOW_TESTS") != "1",
    reason="ставит эфемерный venv + pytest; включается PROBE_SLOW_TESTS=1",
)
def test_install_and_test_red_on_missing_dep(tmp_path: Path) -> None:
    """Тест импортирует незадекларированный пакет → tests_pass=False,
    не solved. Это ровно кейс исторического ложного task_solved."""
    _write(
        tmp_path,
        "pyproject.toml",
        """
        [build-system]
        requires = ["hatchling"]
        build-backend = "hatchling.build"

        [project]
        name = "notes"
        version = "0.0.0"
        requires-python = ">=3.11"
        dependencies = []
        """,
    )
    _working_notes_tree(tmp_path)
    _write(
        tmp_path,
        "tests/test_cli.py",
        "import click  # незадекларированная зависимость\n\ndef test(): assert True\n",
    )
    res = check_notes_cli(tmp_path, run_tests=True)
    assert not res.criteria["tests_pass"].passed
    assert res.solved is False

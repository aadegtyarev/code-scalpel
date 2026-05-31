"""Механические чекеры приёмки для probe-сценариев.

До этого вердикт (`task_solved` / `user_gave_up`) ставился руками
через `finalize --reason`. Это субъективно — и доказуемо ненадёжно:
единственный исторический `task_solved` (662d2bc) на деле **не
собирается** в чистом окружении (тесты импортируют `click`, которого
нет в задекларированных зависимостях `pyproject.toml`). Ручной ярлык
этого не увидел.

Чекер считает вердикт из фактов: ставит проект в эфемерный venv и
гоняет его собственные тесты (поведенческое ядро), плюс несколько
drift-устойчивых структурных проверок. Имя пакета модель выбирает
стохастически (`notes/`, `app.py`, `notes_cli/` …), поэтому чекер
**не хардкодит** структуру — он смотрит на весь дерево источников.

Контракт: `run_checks(scenario, final_tree) -> CheckResult`.
`CheckResult.solved` — объективный аналог старого `task_solved`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Сколько ждём установку проекта и прогон pytest. venv + pip — не
# мгновенны; pytest на мини-CLI — секунды. Запас на холодный pip.
_INSTALL_TIMEOUT_SEC = 240
_PYTEST_TIMEOUT_SEC = 120


@dataclass(frozen=True)
class Criterion:
    """Один проверяемый факт о финальном дереве."""

    passed: bool
    detail: str


@dataclass(frozen=True)
class CheckResult:
    """Итог механической проверки одного прогона.

    `criteria` — все проверки (и поведенческие, и структурные).
    `gating` — подмножество ключей, чьё одновременное прохождение
    означает «задача решена». Структурные проверки (есть ли тесты,
    есть ли пакет) входят в счёт `pass_score`, но не гейтят вердикт:
    можно набросать файлов и не пройти тесты.
    """

    criteria: dict[str, Criterion]
    gating: tuple[str, ...]

    @property
    def pass_score(self) -> int:
        return sum(1 for c in self.criteria.values() if c.passed)

    @property
    def pass_max(self) -> int:
        return len(self.criteria)

    @property
    def solved(self) -> bool:
        """Все gating-критерии присутствуют и прошли. Отсутствующий
        gating-критерий (например `tests_pass` без поведенческого
        прогона) считается непройденным — «не проверено» ≠ «решено».
        Пустой gating ⇒ не решено."""
        if not self.gating:
            return False
        return all(k in self.criteria and self.criteria[k].passed for k in self.gating)

    def to_verdict(self) -> dict[str, Any]:
        """Сериализация в формат `verdict.json`."""
        return {
            "pass_score": self.pass_score,
            "pass_max": self.pass_max,
            "criteria": {
                k: {"passed": c.passed, "detail": c.detail} for k, c in self.criteria.items()
            },
            "mechanical_solved": self.solved,
        }


def _source_py_files(tree: Path) -> list[Path]:
    """Все `.py` проекта кроме тестов и venv-мусора. Имя пакета не
    предполагаем — берём всё, что не под `tests/`/`.venv/`/`build/`."""
    skip_parts = {"tests", ".venv", "venv", "build", "dist", ".git", "__pycache__"}
    out: list[Path] = []
    for p in tree.rglob("*.py"):
        if skip_parts & set(p.parts):
            continue
        out.append(p)
    return out


def _source_text(tree: Path) -> str:
    """Конкатенация исходников (lower-case) для grep-проверок."""
    chunks: list[str] = []
    for p in _source_py_files(tree):
        try:
            chunks.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks).lower()


def _has_package(tree: Path) -> Criterion:
    files = _source_py_files(tree)
    # Фикстура стартует пустой — любой нетривиальный .py вне tests/
    # это уже построенный код. Фильтруем совсем пустые файлы.
    nonempty = [p for p in files if p.read_text(encoding="utf-8", errors="replace").strip()]
    return Criterion(
        passed=bool(nonempty),
        detail=f"{len(nonempty)} непустых .py-файла(ов) с исходным кодом",
    )


def _has_four_commands(tree: Path) -> Criterion:
    text = _source_text(tree)
    commands = ("add", "list", "search", "delete")
    # Глагол как отдельное слово ИЛИ голова snake_case-идентификатора:
    # ловим и `"add"`-субкоманду, и `def add_note(...)`. `\badd\b` один
    # промахивался по `add_note` (`_` — словесный символ → нет границы).
    found = [c for c in commands if re.search(rf"\b{c}(?:_|\b)", text)]
    missing = [c for c in commands if c not in found]
    return Criterion(
        passed=not missing,
        detail=("все 4 команды упомянуты" if not missing else f"нет упоминания: {missing}"),
    )


def _has_json_storage(tree: Path) -> Criterion:
    text = _source_text(tree)
    # json.dump/load — сериализация; ".json" — путь к хранилищу.
    has_json_api = "json.dump" in text or "json.load" in text
    has_json_path = ".json" in text
    passed = has_json_api and has_json_path
    return Criterion(
        passed=passed,
        detail=(
            "json-сериализация + .json-хранилище найдены"
            if passed
            else f"json.dump/load={has_json_api}, .json-путь={has_json_path}"
        ),
    )


def _has_docs(tree: Path) -> Criterion:
    """Документация проекта: непустой README (.md/.rst/.txt) ИЛИ
    докстринги в исходниках. Цель скальпеля — рабочий проект *с
    документацией*, поэтому это gating-критерий, а не косметика."""
    readmes = [
        p
        for p in tree.glob("README*")
        if p.is_file() and len(p.read_text(encoding="utf-8", errors="replace").strip()) >= 40
    ]
    if readmes:
        return Criterion(True, f"README найден ({readmes[0].name})")
    # Фолбэк: модульные/функциональные докстринги в исходниках.
    docstring_re = re.compile(r'"""|\x27\x27\x27')
    documented = [
        p for p in _source_py_files(tree) if docstring_re.search(p.read_text("utf-8", "replace"))
    ]
    if documented:
        return Criterion(True, f"README нет, но есть докстринги в {len(documented)} файле(ах)")
    return Criterion(False, "ни README, ни докстрингов")


def _has_tests(tree: Path) -> Criterion:
    test_dir = tree / "tests"
    test_files = [
        p
        for p in tree.rglob("test_*.py")
        if p.read_text(encoding="utf-8", errors="replace").strip()
    ]
    return Criterion(
        passed=bool(test_files),
        detail=(
            f"{len(test_files)} тест-файл(ов)"
            if test_files
            else f"тест-файлов не найдено (tests/ exists={test_dir.exists()})"
        ),
    )


_ACC_TOKEN = "ACC_PROBE_NOTE_7Q2"


def _find_cli_launchers(tree: Path, python: str | None = None) -> list[list[str]]:
    """Способы запустить проект КАК CLI, drift-устойчиво к имени/структуре.
    `python -m <pkg>` для пакетов с `__main__.py`; `python <file>` для
    модулей с реальной точкой входа (`__main__` + argparse/sys.argv/
    click/typer). Модуль без точки входа сюда НЕ попадёт — это и ловит
    «функции есть, а CLI нет».

    `python` — путь к интерпретатору (по умолчанию sys.executable).
    Если передан venv-питон, модуль уже установлен через pip и
    src-layout прозрачен без всякого sys.path-хака."""
    py_bin = python or sys.executable
    launchers: list[list[str]] = []
    for main in tree.rglob("__main__.py"):
        if {"tests", "__pycache__"} & set(main.parts):
            continue
        parts = main.parent.relative_to(tree).parts
        # src-layout: первый компонент — "src" без __init__.py.
        # Генерируем модуль без "src." — pip install -e . уже поставил
        # пакет в venv и он виден напрямую.
        if parts and parts[0] == "src" and not (tree / "src" / "__init__.py").exists():
            parts = parts[1:]
        mod = ".".join(parts)
        if mod:
            launchers.append([py_bin, "-m", mod])
    entry_re = re.compile(r"__main__|argparse|sys\.argv|\bclick\b|\btyper\b")
    for py in _source_py_files(tree):
        text = py.read_text("utf-8", "replace")
        if "__main__" in text and entry_re.search(text):
            launchers.append([py_bin, str(py.relative_to(tree))])
    return launchers


def _json_storage_has(tree: Path, token: str) -> bool:
    for j in tree.rglob("*.json"):
        if "__pycache__" in j.parts:
            continue
        try:
            if token in j.read_text("utf-8", "replace"):
                return True
        except OSError:
            continue
    return False


def check_cli_acceptance(tree: Path) -> Criterion:
    """Авторитетный поведенческий гейт: запускается ли проект КАК CLI
    и реально добавляет/показывает заметку. Независим от тестов модели
    (те циркулярны — модель проверяет сама себя). Ловит ложный solved,
    где `add/list/search/delete` есть функциями + зелёные тесты, но
    `python notes.py add x` не делает ничего (нет argparse-точки входа).
    Контракт интерфейса задаёт сценарий: субкоманды add/list/…, текст
    заметки — позиционный аргумент."""
    with tempfile.TemporaryDirectory(prefix="probe-acc-") as tmp:
        work = Path(tmp) / "proj"
        shutil.copytree(
            tree,
            work,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".git", ".venv", "venv", ".pytest_cache", "*.json"
            ),
        )

        # Ставим зависимости в изолированный venv — без этого click/typer
        # не импортируются и CLI падает с ImportError до первой команды.
        # Передаём venv-питон в _find_cli_launchers: установленный пакет
        # виден напрямую, src-layout не нужно обходить через sys.path.
        # ВАЖНО: venv создаём РЯДОМ с work, не внутри — иначе _source_py_files
        # обходит сотни venv-файлов и получает десятки ложных кандидатов.
        venv = Path(tmp) / ".acc-venv"
        py_bin = sys.executable
        rc, _ = _run([sys.executable, "-m", "venv", str(venv)], work, 60)
        if rc == 0:
            py_bin = str(venv / "bin" / "python")
            pip = [py_bin, "-m", "pip", "install", "-q"]
            rc2, _ = _run([*pip, "-e", ".[dev]"], work, _INSTALL_TIMEOUT_SEC)
            if rc2 != 0:
                _run([*pip, "-e", "."], work, _INSTALL_TIMEOUT_SEC)

        launchers = _find_cli_launchers(work, python=py_bin)
        if not launchers:
            return Criterion(
                False, "нет точки входа CLI (__main__/argparse) — не запускается как CLI"
            )
        for launcher in launchers:
            rc, _out = _run([*launcher, "add", _ACC_TOKEN], work, 30)
            added = _json_storage_has(work, _ACC_TOKEN)
            if rc != 0 and not added:
                continue
            _, list_out = _run([*launcher, "list"], work, 30)
            if _ACC_TOKEN in list_out or added:
                label = " ".join(launcher[1:]) or launcher[0]
                return Criterion(True, f"CLI работает: add→list через `{label}`")
        return Criterion(
            False, f"точка входа есть, но add/list не сработали ({len(launchers)} кандидат(ов))"
        )


def _run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    """Запуск процесса с таймаутом. Возвращает (returncode, tail-вывод).
    Таймаут/ошибка запуска → returncode 124/127 и текст в выводе."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, f"timeout после {timeout}s: {' '.join(cmd)}"
    except OSError as exc:
        return 127, f"не удалось запустить {cmd[0]}: {exc}"
    tail = (proc.stdout + proc.stderr).strip()
    return proc.returncode, tail[-2000:]


def _install_and_test(tree: Path) -> tuple[Criterion, Criterion]:
    """Ставит зависимости проекта в эфемерный venv и гоняет его pytest.

    Возвращает (installable, tests_pass).

    `tests_pass` — поведенческое ядро и единственный гейт-сигнал:
    «зелены ли собственные тесты проекта». pytest в режиме prepend
    сам кладёт корень дерева в sys.path, поэтому пакет импортируется
    даже без сборки wheel — функциональный успех не должен зависеть
    от педантики упаковки.

    `installable` — диагностика (НЕ гейт): собирается ли проект как
    устанавливаемый пакет. Ловит package-name-drift (`notes/` против
    объявленного `notes_cli`) и конфликт setup.py(click) vs
    pyproject(deps=[]) — но рабочий CLI с зелёными тестами проходит и
    при кривой упаковке.
    """
    with tempfile.TemporaryDirectory(prefix="probe-check-") as tmp:
        work = Path(tmp) / "proj"
        # Гигиена входа: рантайм-артефакты прогона (`__pycache__`,
        # `*.pyc`) не должны течь в тест-песочницу — stale-байткод
        # маскирует исходник и даёт ложные негативы. Верификатор
        # обязан сам чистить вход (Глава 41, «12-я точка провала»).
        shutil.copytree(
            tree,
            work,
            ignore=shutil.ignore_patterns(".venv", "venv", ".git", "__pycache__", "*.pyc"),
        )

        venv = work / ".check-venv"
        rc, out = _run([sys.executable, "-m", "venv", str(venv)], work, 60)
        if rc != 0:
            fail = Criterion(False, f"не создать venv: {out}")
            return fail, Criterion(False, "не дошли до тестов — нет venv")

        py = venv / "bin" / "python"
        pip = [str(py), "-m", "pip", "install", "-q"]

        # Раннер: модель могла не объявить pytest — ставим явно.
        _run([*pip, "pytest"], work, _INSTALL_TIMEOUT_SEC)

        # Зависимости проекта best-effort: editable-install по
        # метаданным, иначе requirements.txt. Если не вышло — всё
        # равно гоняем тесты (вдруг проект на одной stdlib).
        rc, out = _run([*pip, "-e", ".[dev]"], work, _INSTALL_TIMEOUT_SEC)
        if rc != 0:
            rc, out = _run([*pip, "-e", "."], work, _INSTALL_TIMEOUT_SEC)
        if rc != 0 and (work / "requirements.txt").exists():
            rc, out = _run([*pip, "-r", "requirements.txt"], work, _INSTALL_TIMEOUT_SEC)
        installable = Criterion(
            passed=rc == 0,
            detail=(
                "проект ставится как пакет"
                if rc == 0
                else f"editable/requirements install не прошёл: {out[-600:]}"
            ),
        )

        rc, out = _run([str(py), "-m", "pytest", "-q"], work, _PYTEST_TIMEOUT_SEC)
        tests_pass = Criterion(
            passed=rc == 0,
            detail=("pytest зелёный" if rc == 0 else f"pytest упал (rc={rc}): {out[-800:]}"),
        )
        return installable, tests_pass


def check_notes_cli(tree: Path, *, run_tests: bool = True) -> CheckResult:
    """Чекер сценария notes_cli: CLI заметок (add/list/search/delete),
    json-хранилище, pytest. `run_tests=False` — только структурные
    проверки (быстро, без venv)."""
    criteria: dict[str, Criterion] = {
        "package": _has_package(tree),
        "four_commands": _has_four_commands(tree),
        "json_storage": _has_json_storage(tree),
        "tests_present": _has_tests(tree),
        "docs": _has_docs(tree),
    }
    # Gating = «рабочий проект с документацией, который реально
    # запускается как CLI». `acceptance` — авторитетный поведенческий
    # гейт (дёргает CLI), независим от тестов модели (циркулярных).
    # `tests_pass`/`acceptance` без `run_tests` в criteria нет, и solved
    # останется False — поведение не проверено. pass_score — диагностика.
    gating = ("four_commands", "json_storage", "docs", "tests_pass", "acceptance")
    if run_tests:
        installable, tests_pass = _install_and_test(tree)
        criteria["installable"] = installable
        criteria["tests_pass"] = tests_pass
        criteria["acceptance"] = check_cli_acceptance(tree)
    return CheckResult(criteria=criteria, gating=gating)


_CHECKERS: dict[str, Callable[..., CheckResult]] = {
    "notes_cli": check_notes_cli,
}


def has_checker(scenario: str) -> bool:
    return scenario in _CHECKERS


def run_checks(scenario: str, final_tree: Path, *, run_tests: bool = True) -> CheckResult | None:
    """Прогнать механический чекер сценария по финальному дереву.

    `None` — для сценария нет чекера (вердикт остаётся ручным, как
    раньше). Так миграция не ломает сценарии без рубрики."""
    checker = _CHECKERS.get(scenario)
    if checker is None:
        return None
    return checker(final_tree, run_tests=run_tests)


__all__ = [
    "CheckResult",
    "Criterion",
    "check_notes_cli",
    "has_checker",
    "run_checks",
]

"""Static check: a written `.py` file actually parses.

Слабая модель регулярно пишет синтаксически битый Python — лишний
хвостовой `")`, незакрытая скобка, оборванный литерал. Файл не
парсится → CLI не запускается И pytest не собирает (rc=2). Одна
кривая строка убивает два гейта сразу, а pytest-traceback про
collection — шумный и непрямой сигнал для модели.

`ast.parse` даёт точную строку и сообщение БЕЗ исполнения (никаких
сайд-эффектов импорта). Самый базовый класс провала — ловим его
раньше тестов и тычем модель носом в конкретную строку.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SyntaxIssue:
    """Синтаксическая ошибка в одном файле."""

    file: Path
    line: int
    message: str


def check_syntax(path: Path | str) -> SyntaxIssue | None:
    """Распарсить файл через `ast.parse`. Вернуть `SyntaxIssue` при
    ошибке, иначе `None`. Не-`.py` и нечитаемые файлы → `None` (нечего
    проверять). Никакого исполнения."""
    p = Path(path)
    if p.suffix != ".py":
        return None
    try:
        source = p.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        ast.parse(source, filename=str(p))
    except SyntaxError as exc:
        return SyntaxIssue(file=p, line=exc.lineno or 0, message=exc.msg)
    return None

"""CHANGELOG.md parser — извлекает последнюю запись о версии."""

import re
from pathlib import Path
from typing import Optional


def parse_changelog(path: str | Path) -> Optional[dict]:
    """Парсит CHANGELOG.md и возвращает данные последней версии.

    Формат (Keep a Changelog):
        ## [version] - YYYY-MM-DD
        ...
        ## [next version] - ...

    Возвращает словарь с ключами:
        version — строка с номером версии (без скобок)
        body    — тело релиза (текст между заголовками)
        date    — строка с датой
    Или None, если ни одна версия не найдена.
    """
    path = Path(path)
    if not path.exists():
        return None

    text = path.read_text(encoding="utf-8")

    # Ищем заголовки ## [version] - date
    # Регулярка: две решётки, пробел, [, номер версии, ], пробел, -, пробел, дата
    version_pattern = re.compile(
        r"^##\s+\[([^\]]+)\]\s*-\s*(.+)$", re.MULTILINE
    )

    matches = list(version_pattern.finditer(text))
    if not matches:
        return None

    # Берём последний (первый по порядку в файле) заголовок
    first = matches[0]
    version = first.group(1).strip()
    date = first.group(2).strip()

    # Тело — от конца первого заголовка до начала следующего (или конца файла)
    body_start = first.end()
    if len(matches) > 1:
        body_end = matches[1].start()
    else:
        body_end = len(text)

    body = text[body_start:body_end].strip()

    return {
        "version": version,
        "body": body,
        "date": date,
    }

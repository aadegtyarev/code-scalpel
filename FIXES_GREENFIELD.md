# Greenfield task fixes

Найдены причины сбоев на задачах «напиши CLI-утилиту с нуля». Нужно исправить 4 вещи.

## 1. Фильтровать placeholder в `_parse_task_files()` — `agent.py:524–545`

Модель иногда пишет `Files: project_map()` вместо реального пути.
Сейчас функция фильтрует только `<...>`, но не строки с `()`.
Результат: задача получает статус `skipped` (не вызвала write_file),
после 4 подряд skips `run_plan` останавливается с `task_not_done`.

**Фикс:** в цикле по `chunk` добавить:
```python
if "(" in p and ")" in p:  # вызов функции, не путь
    continue
```

---

## 2. T001-rewriter в `annotate_plan()` — `agent.py:1659–1709`

TODO в `docs/plan.md:3034`: «annotate_plan может переписать `Files: project_map()`
в реальные пути эвристически». Реализации нет.

**Фикс:** после аннотации Skills проверить T001:
- если `files` пустой или содержит только placeholder-значения →
  принудительно заменить на `["README.md"]`.

---

## 3. Запретить placeholder в `mode_plan.md`

Правило есть: «T001 MUST write README.md». Но модель его игнорирует.

**Фикс:** добавить явный запрет:
```
Files: MUST list only real file paths. Never use tool calls or
descriptions as file names (e.g. `project_map()` is WRONG, `README.md` is correct).
```

---

## 4. GREENFIELD-секция в `mode_code.md`

Промпт заточен под редактирование. Слабая модель не знает порядок
создания файлов и пишет `main.py` раньше `pyproject.toml`.

**Фикс:** добавить раздел перед основным чеклистом:
```
When project_map() returns empty (greenfield):
1. README.md first (spec + all commands with usage examples).
2. pyproject.toml (package name, entry_point, test deps).
3. src/<name>/__init__.py (empty is fine).
4. Core logic files.
5. tests/ — use tmp_path for any file storage, never shared state.
6. Verify: pip install -e . && pytest
```

---

## Что уже исправлено (не трогать)

- `mode_code.md:62–69` — правило write_file для новых файлов vs SEARCH/REPLACE ✅
- `mode_code.md:54–59` — правило изоляции тестов через tmp_path ✅
- `agent_tools.py:753–765` — write_file разрешает `content=""` для новых файлов (v0.14) ✅

# Scenario: c_fix_bug

## Project

`mini_cli_with_bug` — todo-list CLI на typer, JSON-хранилище в
домашней директории. В core.py есть **один реальный баг**: метод
`TodoStore.mark_done` мутирует item в памяти, но не вызывает
`_write(items)` — изменения теряются. Существующий тест
`tests/test_core.py::test_mark_done_flips_flag` падает с понятным
AssertionError.

## User role

Я (Claude) играю роль юзера согласно `memory/user_tone_of_voice.md`
— junior-разработчик, у которого тест падает.

## Workflow по mode'ам

**Turn 1 — `--mode ask`** (диалог-диагностика, без правок):

> «pytest валится. помоги понять что у меня там с этим тестом
> mark_done — какие гипотезы по содержанию core.py?»

Что я ОЖИДАЮ: scalpel в ask режиме читает core.py, читает тест,
формулирует **гипотезу** («mark_done мутирует но не сохраняет»).
**НЕ патчит**.

**Turn 2 — `--mode code`** (реальный фикс через iterative loop):

> «понятно. поправь и закоммить, чтобы тесты прошли»

Что я ОЖИДАЮ: `code_with_retry` → SR-patch / write_file → run_tests
→ retry до 3 раз. На выходе pytest exit 0 + commit landed.

**Опционально Turn 3 — `--mode review`** (проверка):

> «проверь что изменения адекватные»

Independent skeptic-review без правок.

## Что НЕ делать

- В turn 1 (ask) — не просить «поправь». Только диагноз.
- В turn 2 (code) — не объяснять что делать, дать команду «фикси».
- Не подсказывать где конкретно баг в core.py — пусть scalpel
  сам найдёт через read_file.

## Success criteria (mechchecker → verdict.json)

| Критерий | Описание |
|---|---|
| `tests_pass` | `python -m pytest` exit 0 после прогона |
| `commits_landed_ge_1` | хотя бы один git-коммит landed |
| `no_uncommitted_changes` | `git status --porcelain` пусто |
| `fix_in_mark_done` | grep `_write\\(items\\)` в `core.py` mark_done-блоке |

## Зачем этот кейс

Контроль для измерения **разницы** между чистым ask (probe #1)
и правильным ask→code workflow. Если #1 показал «builder
поломал структуру через write_file», то здесь `code_with_retry`
должен починить за 1-2 retry через SR-patch (не overwrite
файла целиком).

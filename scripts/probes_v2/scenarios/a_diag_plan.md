# Scenario: a_diag_plan

## Project

`mini_cli` (рабочий todo-CLI). Я играю непрофессионального
заказчика, у которого есть идея «ярлыки на задачах + фильтрация
в list».

## User role

Согласно `user_tone_of_voice.md`: короткие реплики строчными,
без вежливости. На технические вопросы — «не знаю / реши сам».

## Workflow по mode'ам

**Turn 1 — `--mode ask`** (обсуждение идеи, без правок):

> «хочу добавить в этот мини todo-cli ярлыки на задачах. типа
> важное / срочное / личное. чтоб можно было фильтровать в list.
> глянь что у меня там есть, разберись как лучше встроить»

Что я ОЖИДАЮ: scalpel дёргает project_map / read_file, читает
структуру, возвращает обсуждение «у тебя есть TodoStore, можно
добавить поле labels…». Может предложить варианты структуры
(одиночный label vs список). НЕ пишет TASKS.md, НЕ патчит.

**Turn 2 — `--mode plan`** (генерация TASKS.md в DSL):

> «ок. разложи это в TASKS.md как у нас принято, чтобы можно
> было пройтись пунктами»

Что я ОЖИДАЮ: scalpel генерирует `.code-scalpel/TASKS.md` через
write_file **в нашем DSL** (с `[_] T001:`, `Files:`, `Test command:`,
`Acceptance:`). Если научится — это сильно отличается от probe #2
где он генерировал свободный markdown.

**Turn 3 — `probe go`** (автоматическая реализация):

scalpel сам идёт по TASKS.md через `run_plan` → `code_with_retry`
для каждой task. Не пишу реплику, просто `probe go <run-id>`.

## Что НЕ делать

- В turn 1 (ask) — не просить «составь план», только обсуждение.
- В turn 2 (plan) — не реализовывать (это для go).
- Не диктовать имена полей / структуру — scalpel сам решает.

## Success criteria (mechchecker → verdict.json)

| Критерий | После какого turn'а |
|---|---|
| `tasks_md_present` | после turn 2 (plan) |
| `tasks_count_ge_3` | после turn 2 |
| `tasks_have_required_fields` (Files/Tests/Acceptance) | после turn 2 |
| `paths_valid` (относительные, в проекте) | после turn 2 |
| `pytest_passes_after_go` | после go: новые тесты + старые проходят |
| `commits_landed_during_go` | после go |

## Зачем этот кейс

Контроль для measurement правильного workflow vs `ask`-only.
В probe #2 я просил TASKS.md в ask mode — получил свободный
markdown не в DSL. Здесь plan mode должен дать формат, плюс
`go` реализует план автоматически — это полный e2e цикл «идея →
рабочий код» который scalpel должен уметь.

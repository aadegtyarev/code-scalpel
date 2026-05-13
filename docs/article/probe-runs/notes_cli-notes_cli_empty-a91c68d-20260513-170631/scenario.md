# Scenario: notes_cli (universal task across all versions)

Одна задача на всю historical-серию. Реплики юзера — те же на
каждой версии (это даёт сопоставимость). Отличается только
**куда дойдёт** scalpel: см. `reached_level` в verdict.json.

## Project

**Чистая директория** (без fixture'ы). Юзер хочет с нуля
собрать новый CLI. Это значит fixture для probe — пустая папка
с минимальным `pyproject.toml` (чтобы scalpel понимал, что
проект python'овский) и `.git` (для коммитов в L3+).

## User role

Я (Claude) играю юзера согласно `user_tone_of_voice.md`. Цели:
- Дать **одну и ту же** реплику на старте каждого прогона
- Реагировать минимально и сопоставимо на типичные ходы scalpel'а

## Базовая реплика (Turn 1 на каждом прогоне)

> хочу собрать python-CLI для заметок: команды add, list, search, delete. json-storage, pytest. спроектируй и реализуй с тестами. если есть архитектурные вопросы — задай.

Mode: `ask` (на старых версиях ask тянет, на новых — выбор за
scalpel'ом и я подкручиваю mode на следующих turn'ах по
поведению).

## Reference replies на типичные ходы scalpel'а

| Что scalpel сделал | Моя реакция (next turn) |
|---|---|
| Дал план словами в reply | «ок, теперь покажи код для main.py и core.py» (mode=ask или code) |
| Дал план + код через SR в reply | «отлично, создай файлы и положи на диск чтоб pytest запускался» (mode=code) |
| Создал файлы | «закоммить и составь TASKS.md по плану в нашем DSL» (mode=plan) |
| Создал TASKS.md | «давай /go, выполни» (`probe go`) |
| Задал архитектурный вопрос (1 ход) | отвечаю по существу одной фразой, не диктую решение |
| Задал ≥3 вопроса подряд без действий | «давай ты сам решай что лучше» |
| Запутался / семантическая петля | финализирую `user_gave_up`, фиксирую level reached |

## Что НЕ говорю

- Не предлагаю конкретные имена файлов / классов / методов
- Не диктую структуру JSON (что в storage)
- Не подсказываю про typer / argparse / click — пусть выберет
- Не «расскажи про твой проект» (на v0.3 нет читалки)

## Levels (отметки прогресса)

| Level | Достижение |
|---|---|
| L1 | связный план в reply, словами |
| L2 | + код через SR в reply |
| L3 | + файлы на диске |
| L4 | + TASKS.md в нашем DSL |
| L5 | + `/go` (run_plan) прошёл хоть одну task |
| L6 | + fork-точка («какой стек?», «json vs SQLite?») разрешена осмысленно |
| L7 | + fork ушёл в upstream gemma, override/confirm зафиксирован |

В `verdict.json.reached_level` — максимальный достигнутый.

## Критерии остановки

- task_solved: достиг L5+ (TASKS.md выполнен в `/go`) с минимально работающим CLI
- partial: достиг L1-L4, остановился сам или scalpel запутался
- user_gave_up: семантическая петля или >15 turn'ов без прогресса
- error: инфраструктура / runner-incompat

## Mechcheckers

| Поле verdict | Как проверять |
|---|---|
| `reply_present` | turn 1 вернул не-пустой reply |
| `plan_in_reply` | reply содержит явный план: ≥3 нумерованные/буллет точки |
| `sr_in_reply` | reply содержит `<<<<<<< SEARCH` или fenced python с хотя бы одним именем файла |
| `files_on_disk` | в `final_tree/` появилось ≥2 python файла |
| `tasks_md_present` | `final_tree/.code-scalpel/TASKS.md` существует |
| `tasks_md_in_dsl` | в TASKS.md есть `## [_] T` заголовки + Files/Test command |
| `pytest_exit_0` | pytest в `final_tree` проходит |
| `fork_observed` | в `chat.jsonl` есть assistant-turn с fork-question |
| `upstream_observed` | в `meta.json.adaptations` нет upstream-missing + в логах swap |

`reached_level` — derived: max level где все нужные checker'ы True.

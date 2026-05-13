# Scenario: notes_cli — единый plan→go workflow

Одна задача на все версии v0.3+. Реплики и команды — те же.
Меняется только что **модель смогла сделать** в этом workflow.

## Project

`fixtures/notes_cli_empty/` — пустая dir + минимальный pyproject +
`tests/__init__.py`. Scalpel строит проект с нуля.

## User role

Я (Claude) играю юзера согласно `user_tone_of_voice.md`. Цели:
дать **одну и ту же** последовательность команд на каждом тэге,
наблюдать **до какого level** дошёл scalpel.

## Канонический workflow

Workflow повторяет TUI: `/mode plan` → дать задачу → проверить
TASKS.md → `/loop on` → `/go`. В probe-runner это:

### Step 1: `step --mode plan` (задача)

> «хочу собрать python-CLI для заметок: команды add, list, search, delete. json-storage, pytest. спроектируй и реализуй с тестами. если есть архитектурные вопросы — задай.»

Что происходит:
- `agent.ask(task, mode="plan")` подмешивает `_PLAN_MODE_ADDENDUM`
  («производи TASKS.md в DSL `## T001: ...`, no SR/code, 3-7 задач»)
- Если модель ответит в правильном DSL — `_maybe_save_plan(reply)`
  сохранит `.code-scalpel/TASKS.md` автоматически
- Если ответит вне формата (как часто бывает на ранних версиях) —
  TASKS.md **не** сохранится, плохо. Это сам по себе результат.

### Step 2: проверка TASKS.md

Чисто инспекция — смотрим `workdir/.code-scalpel/TASKS.md`. Если
он есть → можем идти на /go. Если нет → даём **ещё один** plan-turn:
«не понял — пиши именно в формате как у нас принято в TASKS.md,
с `## T001:` заголовками и полями Files / Acceptance / Test command».

Это **подсказка про формат**, но в **plan mode** это допустимо —
формат и есть то что plan mode учит, мы не подсказываем содержание.

### Step 3 (опционально, если поддерживается): `step --mode ask "/loop on"`

Это **toggle `iterative_patch_loop`** который на всех версиях
выключен по default. **Если** руками не включить — `code_with_retry`
будет одношаговым (без retry).

В probe мы сейчас передаём `force_loop=True` через kwargs (на
старых версиях параметр отсутствует — compat-shim его отбросит,
поведение деградирует до single-shot).

### Step 4: `probe go`

`agent.run_plan()` ходит по TASKS.md, на каждой задаче запускает
`code_with_retry(mode="code", force_loop=True)`.

**Что произойдёт зависит от capabilities тэга:**

| Версия | Что доступно в `code_with_retry` | Что результат |
|---|---|---|
| v0.3-v0.4 | SR-parser, без write_file. Iterative loop **не** работает (один shot) | На задачах «создать новый файл» — может сработать через SR с пустым SEARCH; на «изменить» — да |
| v0.5 | + iterative loop инфра (но default off) | force_loop=True заработает, retry поедет |
| v0.6 | + force_loop kwarg landed | то же что v0.5 |
| v0.7+ | + write_file tool, project_map, bwrap sandbox | модель может выбрать write_file для создания файлов |
| v0.8+ | + narrow passes / annotate / review | annotate автоматически обогащает TASKS.md |
| v0.9+ | + machine guards (files exist, tests pass, commit landed) | run_plan жёстко проверяет каждую задачу |
| v0.10+ | + Fork API на архитектурных решениях | модель сама может попросить fork |
| v0.12+ | + UpstreamPendingQueue / swap | возможна делегация наверх |

## Levels (отметки прогресса)

В `verdict.json.reached_level` пишем максимально достигнутый:

| Level | Достигнуто |
|---|---|
| **L0** | модель вообще не ответила / ошибка инфры |
| **L1** | связный план в reply (текст) — но **не в DSL** |
| **L2** | TASKS.md в нашем DSL сохранён на диск (`_maybe_save_plan` сработал) |
| **L3** | `/go` запустился, хотя бы 1 task пошла в `code_with_retry` |
| **L4** | хотя бы 1 task **done** (tests passed + commit landed после неё) |
| **L5** | весь план выполнен `run_plan.stopped_reason="all_done"`, pytest в final_tree зелёный |
| **L6** | (v0.10+) fork сгенерировался и разрешён |
| **L7** | (v0.12+) fork ушёл в upstream, override/confirm |

L2 — первая граница «формат плана понят». Без L2 нет смысла идти на go.

## Минимальная последовательность probe-команд

```bash
ID=$(probe start notes_cli notes_cli_empty)

# Step 1: plan
probe step $ID "хочу собрать python-CLI для заметок: команды add, list, search, delete. json-storage, pytest. спроектируй и реализуй с тестами. если есть архитектурные вопросы — задай." --mode plan

# Step 2: проверить TASKS.md — если нет, дать корректирующий turn
[ -f docs/article/probe-runs/$ID/.workdir/.code-scalpel/TASKS.md ] || \
  probe step $ID "не понял — пиши именно в формате как у нас принято: ## T001: <title> с полями Files / Acceptance / Test command. 3-7 задач." --mode plan

# Step 3: /go
probe go $ID

# Step 4: finalize
probe finalize $ID --reason=task_solved   # или user_gave_up / error
```

## Что НЕ говорю

- Не диктую структуру JSON
- Не упоминаю конкретные библиотеки (typer / argparse / click)
- Не подсказываю имена файлов / классов / методов
- Не упоминаю `/loop` (это **архитектурная** особенность — если default off мешает, фиксируем как наблюдение, не лечим репликами)
- На задачи модели «какой формат?», «argparse или click?» — отвечаю «решай сам / как тебе удобнее»

## Reference replies на типичные ходы scalpel'а

| Что scalpel сделал | Моя реакция |
|---|---|
| Задал арх. вопрос (1-2 раза подряд) | отвечаю по существу одной фразой |
| Задал ≥3 вопроса без действий | «давай ты сам решай» |
| Дал план словами в reply, **не в DSL** | следующим turn'ом в plan mode прошу формат |
| Сохранил TASKS.md в DSL | сразу идём `probe go` |
| Запутался / семантическая петля | финализирую `user_gave_up`, level fixed |
| `probe go` дал `stopped_reason=no_tasks` | TASKS.md не сохранился — фиксируем L1 |
| `probe go` дал `all_done` | проверяю final_tree pytest → L5 если зелёный |
| `probe go` дал `max_failures` | смотрю на каком task'е застряло, level L3-L4 |

## Критерии остановки

- task_solved: L5+ (план выполнен + pytest зелёный)
- partial: L1-L4 (фиксируем где остановилось)
- user_gave_up: семантическая петля или >15 turn'ов без прогресса
- error: инфраструктура / runner-incompat не отвалила корректно

## Mechcheckers (для verdict.json.criteria)

После finalize запускаются:

| Поле | Как проверять |
|---|---|
| `plan_present` | reply turn 1 не пустой |
| `tasks_md_in_dsl` | в `final_tree/.code-scalpel/TASKS.md` есть `## T001:` + Files/Test/Acceptance |
| `go_executed` | в `metrics.json` `commits_landed > 0` или есть событие `go.end` в timing |
| `tasks_completed_ge_1` | run_plan вернул tasks_completed ≥ 1 |
| `pytest_passes_final` | в final_tree запустился pytest → exit 0 |
| `fork_observed` | (v0.10+) в `chat.jsonl` или `tools.jsonl` следы fork resolve |
| `upstream_observed` | (v0.12+) в meta.adaptations нет upstream-missing + в timing swap-события |

`reached_level` — derived: max level где все нужные checker'ы True.

## Почему это правильно

В пилот-серии я **везде шёл `--mode ask` → `--mode code`** без
`plan`, без `probe go`. Это **половина workflow**: модель писала
fenced ```python``` юзеру, applier ничего не применял, файлы не
появлялись. Это не баг scalpel'а — это моя методологическая
ошибка.

Этот сценарий повторяет канонический TUI workflow:
`/mode plan` → задача → `/loop on` → `/go`. Так юзер реально
работает со scalpel'ом. И **сам scalpel** через `agent.run_plan`
+ `code_with_retry` сам выберет нужные инструменты на каждой
версии — write_file где есть, SR где нет.

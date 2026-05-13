# Evaluation: notes_cli × v0.3.0 (baseline)

## Reached level: **L1**

Связный план в reply, словами. Дальше не пошёл.

## One-liner

v0.3 baseline: L1 reached. Дал план + написал код через fenced ```python``` (не SR), `code mode` зациклился — повторил тот же reply вместо применения. 11k prompt tokens, 0 tool calls, 0 файлов на диске.

## Trajectory

- **Turn 1 (ask)** базовая реплика: scalpel дал план в reply (структура `notes_cli.py` + `storage.py` + `tests/`), задал 2 архитектурных вопроса (формат JSON, argparse?). Tool calls 0.
- **Turn 2 (ask)** «массив объектов да. argparse норм.»: scalpel выдал большой reply (4.4k chars) с кодом через fenced ```python``` блоки на 4 файла. **НЕ SR-блоки** — applier этого не применит. Файлы на диск не попали.
- **Turn 3 (code)** «сохрани файлы»: scalpel **повторил Reply 2 слово в слово** (4464 vs 4462 chars). Семантическая петля.

## Adaptations (degraded features на v0.3)

| Что упало | Что значит |
|---|---|
| `Runtime.__init__ ... 'upstream_profile'` | upstream-API не существует |
| `ask(on_tool_executed=...)` не поддерживается | tools.jsonl пуст — слепы по tool calls |
| `code_with_retry(on_tool_executed=...)` не поддерживается | то же для code mode |
| `code_with_retry(force_loop=...)` не поддерживается | iterative loop без force_loop |

## Хорошо

- **Связный план с первого turn'а** — модель сама предложила разбиение на 2 файла + tests/. Не идиотское.
- **Архитектурные вопросы задаёт** — модель **не действует наобум**, спрашивает. Это работает.
- **Цена низкая** — 11k tokens / 3 turn / 225 сек.

## Плохо

- **Ноль tool calls.** Модель не дёргает read_file / list_files — она вообще «не знает что есть инструменты» (или системник их не активирует на v0.3).
- **Fenced ```python``` вместо SR**: код есть, но в формате который applier не понимает. На v0.3 пайплайна «модель → SR → applier → файлы» ещё не сложилось.
- **Code mode не помог**: `code_with_retry` v0.3 без `force_loop` сделал 1 retry → повтор предыдущего reply, не патч.

## Гипотезы о причинах

- Системник v0.3 не упоминает SR-формат — модель эмитит «обычный» код для человека.
- Tool-loop не интегрирован — отсутствие `on_tool_executed` параметра тому подтверждение.
- `code_with_retry` на v0.3 — пустая обёртка над `ask` с одним retry, без iterative SR-parsing.

## Архитектурный smell-check

Baseline нашей кривой: «как scalpel выглядит **до** tool-loop, **до** SR, **до** write_file, **до** iterative loop». Каждая следующая версия будет добавлять кусочки. Это будет **прямое доказательство** тезиса «инструмент важнее модели» — та же 14b на v0.3 пишет fenced код юзеру, на main дёргает project_map. Разница не в модели, а в **обвязке**.

## Трудозатраты

3 turn'а, 11k tokens, 225 сек wall. Дёшево, ничего не работает. Это и есть baseline.

## Legacy probe pack v0.3.0

`docs/article/probe-runs/legacy/v0.3.0/`:

| Probe | Result | Время |
|---|---|---|
| `probe.py` | **7/9** passed (basic /ask вопросы) | 178 сек |
| `probe_code.py` | ✓ tests green (один простой fix `calc.add`) | 12 сек |
| `probe_recipes.py` | skipped — отсутствует в `scripts/` v0.3 | — |
| `probe_forks.py` | skipped (Fork API нет) | — |
| `probe_fork_reviewer.py` | skipped | — |
| `probe_e2e_forks.py` | skipped | — |

Из probe.py отказы видны: «Извините, но я не могу найти файл
Session.py» — модель **не дёргает project_map**, отказывается
вместо поиска. Подтверждает наблюдение из live-прогона.

## Список дальнейших действий

(Не правки сейчас — диагностика.)

- Первая точка historical-серии. Сравнений нет — v0.4 даст первое.
- adaptations в `meta.json.adaptations` — карта «что появилось когда» для статьи 6.
- Legacy probe pack: на v0.3 существуют только `probe.py` и `probe_code.py`. На следующих тэгах появятся ещё.

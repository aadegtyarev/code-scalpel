# Evaluation: notes_cli × v0.12.0 — UpstreamPendingQueue + swap

## Reached level: **L3** (= v0.10/v0.11, регресс persists)

Live регресс плана воспроизводится третий раз подряд (v0.10,
v0.11, v0.12). UpstreamPendingQueue и swap ортогональны notes_cli.
Legacy: **probe.py регресс 9/9 → 7/9**, **probe_e2e_forks fail** —
два регресса на смежных осях.

## One-liner

v0.12: L3, тот же регресс что v0.10/v0.11 — T001 «Проанализировать
существующий проект» с `Files: None (yet)`, T002 наконец-то с
реальными Files, но до T002 не дошло. 4 LLM requests, 71s, 0
write_file. Legacy сдвинулся: **probe.py 9/9 → 7/9 регресс**
(тоже впервые с v0.5), **probe_e2e_forks NEW но fail на T001**.

## По сравнению с v0.11.0

| Метрика | v0.11 | **v0.12** |
|---|---|---|
| reached_level | L3 | L3 = |
| LLM requests | 4 | 4 = |
| prompt_total | 20k | 20k = |
| tool_calls | 4 | 4 = |
| write_file | 0 | 0 = |
| commits | 0 | 0 = |
| wall_sec | 80 | **71** (-11%) |

**Третий подряд идентичный live-результат**: L3 / 4 requests /
0 write_file / 71-80 секунд. Это **закреплённый системный
регресс** v0.10+.

## Что нового в v0.12

Из git log v0.11.0..v0.12.0:
- **UpstreamPendingQueue** — fork-вопросы накапливаются в queue,
  flush'атся batch'ем
- **LM Studio model swap orchestration** — explicit load/unload
  через REST API
- **OperationCard widget** — TUI улучшение
- **/escalate** slash-команда

Все эти изменения **не влияют** на notes_cli плановый сценарий.
Но **legacy probe.py регрессировал** — что-то в общей цепочке
снова поползло.

## Что произошло на T001

Идентично v0.11:
1. Plan: T001 «Проанализировать существующий проект»,
   `Files: None (yet)`. **Регресс persists.**
2. annotate_plan +2: добавил Skills.
3. project_map() → видит pyproject.toml + tests.
4. Модель: «понятно, идём дальше».
5. T001 skipped → stop.

Интересно: **T002 уже content-aware** (`Files: notes.json, app.py,
tests/test_app.py`). Но run_plan стопает на первой skipped task'е,
**не пускает** к T002.

Гипотеза: если **скипать «анализ» task'и** в run_plan без штрафа,
модель добралась бы до T002 и сделала write_file. Это
архитектурное решение для **post-v0.12** работы.

## Архитектурный smell-check

v0.12 — **финальный тэг серии**. Главный вывод:
- **Live регресс v0.10-v0.12** — это **3 версии подряд** один и
  тот же паттерн. Не флуктуация, не temperature.
- annotate_plan **постоянно** не переписывает «анализ» в action.
- run_plan stops on first skipped → не даёт пройти к task'ам с
  реальными Files

Это **главный архитектурный долг** к v0.13: либо переписать
annotate_plan, либо разрешить skip-without-stop, либо изменить
plan-mode prompt чтобы не генерировать «анализ» task'и.

## Legacy probe pack v0.12.0 — двойной регресс

| Probe | v0.10 | v0.11 | **v0.12** |
|---|---|---|---|
| `probe.py` | 9/9 | 9/9 | **7/9** ↓↓ (регресс) |
| `probe_code.py` | ✓ 1att | ✓ 1att | **✓ 1att** = |
| `probe_recipes.py` | 2/3 | 3/3 | **2/3** ↓ |
| `probe_forks.py` | 4/4 | 4/4 | **4/4** = |
| `probe_fork_reviewer.py` | — | 3/3 | **3/3** = |
| `probe_e2e_forks.py` | — | — | **FAIL** NEW |

**Двойной регресс**:
- probe.py: 9/9 → **7/9** (-2). Что-то в basic ask режиме v0.12
  снова просело (как было на v0.5).
- probe_recipes: 3/3 → **2/3** (тот же что на v0.10, опять
  потерян после recovery v0.11)
- probe_e2e_forks: новый probe — **fails** (T001 failed, plan
  сгенерирован но не выполнен)

То есть v0.12 принёс **новые capabilities** (UpstreamQueue, swap,
escalate) но **подёргал смежные оси**:
- probe.py — басовый ask просел
- probe_recipes — recovery v0.11 не удержали
- probe_e2e_forks — own probe **не работает**

## Итог серии v0.10-v0.12 — fork-эпоха

Три тэга fork-фич:
- v0.10: Fork API → probe_forks ✓, probe_recipes регресс
- v0.11: ReviewedAuto → probe_fork_reviewer ✓, recipes recover
- v0.12: UpstreamQueue → e2e_forks **fail**, probe.py регресс

**Главный паттерн**: каждый fork-релиз закрывает свою узкую ось,
но **проседает на смежных**. И **live план** регрессирует к v0.7
поведению все три релиза подряд.

Это **сильнейший аргумент** для probe-suite v2 в CI: без него
эти регрессы остались бы невидимыми до production'а.

Что **дальше для main**: проверить если v0.13/main починили
plan-mode и вернули L3+ как было на v0.8/v0.9.

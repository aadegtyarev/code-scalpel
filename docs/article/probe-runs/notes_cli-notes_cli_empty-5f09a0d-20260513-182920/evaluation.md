# Evaluation: notes_cli × v0.4.0

## Reached level: **L3** (= v0.3)

Подтверждение baseline'а. Cosmetic release без изменений в
plan/code mode.

## One-liner

v0.4: L3 как v0.3. TASKS.md 7 задач сохранён в DSL, run_plan all_done, 7/7 skipped. Системник тот же что v0.3 — нет `_CODE_MODE_ADDENDUM`, модель в run_plan task'ах не получает инструкции что делать.

## По сравнению с v0.3.0

| Метрика | v0.3 | v0.4 |
|---|---|---|
| reached_level | L3 | L3 = |
| TASKS.md задач | 6 | 7 |
| skipped | 6/6 | 7/7 |
| LLM requests | 9 | 12 (+3) |
| prompt_total | 44k | 59k (**сумма** по запросам) |
| prompt_peak | 6.8k | 6.6k (**один запрос**, в 16k context — норма) |
| tool_calls | 0 | 0 |
| wall_sec | 198 | 216 |

`prompt_total` вырос пропорционально количеству запросов; **peak
тот же**, размер системника не менялся.

## Архитектурный smell-check

v0.4 — release без архитектурных изменений в нашем pipeline.
Подтверждает что baseline-frame {v0.3, v0.4} стабилен. Это
**ожидаемо** при отсутствии `_CODE_MODE_ADDENDUM` — модель просто
повторяет поведение v0.3.

## Legacy probe pack v0.4.0

| Probe | v0.3 | v0.4 |
|---|---|---|
| `probe.py` | 8/9 | **8/9** = |
| `probe_code.py` | ✗ 3att red | **✗ 3att red** = |
| остальные | skipped | skipped |

Идентично v0.3 в обоих осях.

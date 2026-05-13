# Evaluation: notes_cli × v0.4.0

## Reached level: **L3** (= v0.3)

Идентично baseline'у. v0.4 — cosmetic release без архитектурных
изменений в plan/code mode.

## One-liner

v0.4: L3 как v0.3. plan→TASKS.md (7 задач) → go → 7/7 skipped, all_done 0 done. То же что v0.3 baseline.

## По сравнению с v0.3.0

| Метрика | v0.3 | v0.4 |
|---|---|---|
| reached_level | L3 | **L3** = |
| user_turns (plan-step) | 1 | 1 |
| TASKS.md задач | 6 | 7 |
| run_plan stopped_reason | all_done | all_done |
| tasks_completed | 0 | 0 |
| tasks skipped | 6/6 | 7/7 |

## Хорошо

- Plan-pipeline стабильно работает: TASKS.md сохранён в DSL.
- Compat-shim работает: те же 6 adaptations что v0.3.

## Плохо

- code-flow не сдвинулся — модель всё ещё не эмитит SR.

## Архитектурный smell-check

v0.4 — ожидаемая cosmetic точка. Подтверждает baseline-frame
{v0.3, v0.4}: plan-pipeline ✓, code-pipeline ✗.

## Legacy probe pack v0.4.0

| Probe | v0.3 | v0.4 |
|---|---|---|
| `probe.py` | 8/9 | **8/9** = |
| `probe_code.py` | ✗ 3att red | **✗ 3att red** = |
| остальные | skipped | skipped |

Идентично v0.3 в обоих осях.

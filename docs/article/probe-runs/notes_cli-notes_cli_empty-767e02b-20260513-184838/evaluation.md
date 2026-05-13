# Evaluation: notes_cli × v0.6.0 (rename /run → /go)

## Reached level: **L3** (= v0.3-v0.5)

Четвёртая L3 точка. v0.6 — переименование `/run` → `/go` + 4
mode_addenda (vs 2 на v0.3-v0.5). Но это не сдвинуло code-flow:
модель в run_plan task'ах по-прежнему не эмитит SR.

## One-liner

v0.6: L3 как baseline. TASKS.md 7 задач, run_plan all_done, 7/7 skipped. Legacy probe.py восстановился до 8/9 после v0.5 регрессии.

## По сравнению с v0.5.0

| Метрика | v0.5 | v0.6 |
|---|---|---|
| reached_level | L3 | **L3** = |
| TASKS.md задач | 7 | 7 |
| skipped | 7/7 | 7/7 |
| prompt tokens | 7.9k | 50k |
| user_turns | 1 | 1 |

**Замечание**: prompt_tokens вырос с ~8k до 50k. Видимо в v0.6
системник существенно длиннее (новые mode_addenda) — это
ожидаемо при появлении 2 дополнительных режимов.

## Legacy probe pack v0.6.0 — recovery

| Probe | v0.3 | v0.4 | v0.5 | **v0.6** |
|---|---|---|---|---|
| `probe.py` | 8/9 | 8/9 | 6/9 ↓ | **8/9** ↑ recovery |
| `probe_code.py` | ✗ 3att | ✗ 3att | ✓ 1att | **✓ 1att** = |
| `probe_recipes.py` | — | — | 2/3 | 2/3 = |

probe.py восстановился до старого baseline'а после v0.5
регрессии. probe_code стабильно зелёный с landing'а code_with_retry.

## Гипотезы

- **Mode-addenda на v0.6 расширились с 2 до 4** — возможно
  добавились `_CODE_MODE_ADDENDUM` и `_REVIEW_MODE_ADDENDUM`.
  Но **на наш сценарий это не повлияло** — run_plan'овский
  cycle всё ещё не учит модель эмитить SR.

## Архитектурный smell-check

Стабильный baseline-frame {v0.3-v0.6} в live (L3). Все ожидания
теперь — на v0.7, где landed write_file + project_map + bwrap.
**Это** должно дать перелом — либо модель начнёт использовать
write_file (L4+), либо обнаружим что без правильной обвязки
write_file тоже не помогает.

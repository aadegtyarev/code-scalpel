# Evaluation: notes_cli × v0.5.0

## Reached level: **L3** (= v0.3, v0.4)

Third baseline-frame. `code_with_retry` инфра landed (commit
a06e0c9 в v0.5), но **не помогла** на нашей задаче — модель в
run_plan-контексте по-прежнему не эмитит SR-блоки.

## One-liner

v0.5: L3 как v0.3-v0.4. TASKS.md 7 задач → go → 7/7 skipped. code_with_retry landed но без code-mode addendum модель не пишет SR.

## По сравнению с предыдущими

| Метрика | v0.3 | v0.4 | v0.5 |
|---|---|---|---|
| reached_level | L3 | L3 | **L3** |
| TASKS.md задач | 6 | 7 | 7 |
| skipped | 6/6 | 7/7 | **7/7** |

Полная стабильность. v0.5 — переход с `code_with_retry` в коде,
но **модель не научена** SR-формату для code-mode.

## Архитектурный smell-check

Три точки подряд L3 — baseline-frame {v0.3, v0.4, v0.5} стабилен.
**Главное** ожидание серии теперь — v0.6/v0.7 где landed
write_file + видимо `_CODE_MODE_ADDENDUM`. Это должно вывести
из L3.

## Legacy probe pack v0.5.0 — interesting split

| Probe | v0.3 | v0.4 | **v0.5** |
|---|---|---|---|
| `probe.py` | 8/9 | 8/9 | **6/9** ↓ (−2) |
| `probe_code.py` | ✗ 3att | ✗ 3att | **✓ 1att** ↑ (recovery) |
| `probe_recipes.py` | — | — | **2/3** (новый) |

**Расхождение между axes**:
- probe_code (узкий SR fix): **починился** с появлением
  code_with_retry — теперь модель эмитит правильный SR-патч
  с первого раза.
- probe.py (basic /ask): **просел** на 2 пункта — видимо
  что-то в системнике v0.5 регрессировало для ask-режима.

Это **первая регрессия в legacy axis** parallel'но с
улучшением другого probe. Архитектурный сдвиг v0.4 → v0.5
имеет цену.

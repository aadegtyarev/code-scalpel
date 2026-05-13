# Evaluation: notes_cli × main — финал серии

## Reached level: **L3** (= v0.10-v0.12, регресс persists)

Live регресс **4 версии подряд** (v0.10, v0.11, v0.12, main).
Legacy: **partial recovery** — probe.py 7/9 → 8/9, probe_recipes
3/3, probe_e2e_forks починили (FAIL → tasks_completed=1). 9/9 на
probe.py всё ещё **не возвращён** к main.

## One-liner

main: L3, тот же plan-mode регресс v0.10+. 4 LLM requests, 73s,
0 write_file — идентично трём предыдущим релизам. **Главный вывод
серии**: между v0.9 и v0.10 что-то поменялось в plan-mode prompt
цепочке, и это не починили до v0.13. Legacy на main стабилен
после v0.12 двойного регресса: probe.py 7/9 → **8/9** (частично),
probe_recipes **3/3 recovered**, probe_e2e_forks **починен**.

## По сравнению с v0.12.0

| Метрика | v0.12 | **main** |
|---|---|---|
| reached_level | L3 | L3 = |
| LLM requests | 4 | 4 = |
| prompt_total | 20k | 20k = |
| tool_calls | 4 | 4 = |
| write_file | 0 | 0 = |
| commits | 0 | 0 = |
| wall_sec | 71 | 73 = |

Live полностью идентичен v0.10-v0.12. **4-я версия подряд**
без сдвига.

## Что нового в main vs v0.12

- v0.12.5 в процессе (Full resume — UpstreamForker полный flow)
- Доп. fixes реактивности UI
- Probe-suite v2 встроен (наш проект)

Plan-mode цепочка **не починена**.

## Что произошло на T001 (idem)

1. Plan: T001 «Проанализировать существующую структуру»,
   `Files: project_map()`. Шаблон сохраняется.
2. annotate_plan x2: добавил Skills.
3. project_map() → видит pyproject.toml + tests.
4. Модель: «понятно, идём дальше».
5. T001 skipped → stop.

Интересно: на main TASKS.md уже **смешанная**:
- T001 «Проанализировать» (analytic — НЕ требует write_file)
- T002 «Создать базовую структуру» (action — Files: notes_cli.py,
  tests/test_notes_cli.py)
- T003-T007 action-oriented

Если бы run_plan skip'ал T001 без stop'а, модель **дошла бы**
до T002 и сделала write_file. Это **архитектурный долг #1** к
v0.13.

## Архитектурный smell-check — финал серии

**Live эволюция reached_level**:
- v0.3-v0.7: L3 (стабильный baseline)
- v0.8: **L3+** (прорыв — 11 write_file, 8 файлов)
- v0.9: L3+ (дешевле)
- **v0.10-main: L3** (регресс persists 4 версии подряд)

**Регресс v0.10+** — главное открытие серии. Закрыли fork-эпоху,
но потеряли action-orientation плана.

**Legacy эволюция** (basic ask probe.py):
- v0.3-v0.4: 8/9
- v0.5: 6/9 (регресс)
- v0.6-v0.7: 8/9 (recovery)
- v0.8-v0.11: **9/9** (рекорд)
- v0.12: 7/9 (регресс)
- main: 8/9 (partial recovery)

То есть **basic ask тоже плавает**, но в более узких пределах
(6-9/9). Live план **более чувствителен** к prompt-цепочке.

## Legacy probe pack main — partial recovery

| Probe | v0.11 | v0.12 | **main** |
|---|---|---|---|
| `probe.py` | 9/9 | 7/9 | **8/9** ↑ partial |
| `probe_code.py` | ✓ 1att | ✓ 1att | **✓ 1att** = |
| `probe_recipes.py` | 3/3 | 2/3 | **3/3** ↑ recovery |
| `probe_forks.py` | 4/4 | 4/4 | **4/4** = |
| `probe_fork_reviewer.py` | 3/3 | 3/3 | **3/3** = |
| `probe_e2e_forks.py` | — | FAIL | **ok** (1 task done) |

**Победы main**:
- probe_recipes 2/3 → 3/3 (recovery)
- probe_e2e_forks FAIL → ok (1 task completed — fork-flow работает)

**Не до конца**:
- probe.py 7/9 → 8/9 (но не 9/9 как v0.8-v0.11)
- Live план остался регрессом

## Главные открытия серии

1. **v0.7 → v0.8 watershed** — annotate_plan переписал «анализ»
   в action → L3 → L3+. Можно подтвердить **архитектурно
   нелинейный** прогресс.
2. **v0.10-main регресс** — plan-mode не починили. probe-suite
   обнаружил это что было бы невидимо в CI.
3. **Fork-эпоха** v0.10-v0.12: каждый релиз — fork-фича +
   побочный регресс смежной оси. Trade-off обычный для крупных
   релизов.
4. **L4 нигде не достигнут** — даже на v0.8/v0.9 модель не
   делает финальный `git commit`. Это **отдельный архитектурный
   долг** — нужен auto-commit hook или explicit /go-commit fence.

## Главные архитектурные долги к v0.13

1. **annotate_plan rewriter** — должен переписывать «Проанализировать
   структуру» в «Создать X, Y, Z» (если есть real-file Files в
   плане). Иначе run_plan вечно skip'ает T001.
2. **skip-without-stop в run_plan** — analytic task'и не должны
   стопать pipeline. Skip → продолжить к T002.
3. **auto-commit hook** — после write_file и pytest green
   автоматически делать git commit. Иначе L4 не достичь.

## Подытог серии

11 версий: v0.3 → main. Главные точки прогресса — v0.7
(write_file landed) и **v0.8 (annotate_plan auto)**. Главная
точка регресса — **v0.10** (Fork API ввёл побочный регресс
plan-mode который не починили).

probe-suite v2 как regression-test **доказал свою ценность**:
без него регресс v0.10-main остался бы невидимым 3+ релиза подряд.

Это и есть **главный аргумент статьи** — probe-suite не для
показа silly LLM ошибок, а для **видения архитектурного
дрейфа** между релизами.

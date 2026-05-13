# Evaluation: notes_cli × v0.9.0 — machine guards landed

## Reached level: **L3+** (= v0.8, но дешевле)

Machine guards (mkdir, empty content, AST empty-test detector,
lint pass, import-graph check) — но **0 commits** всё ещё. T001
помечен failed уже на первой задаче (быстрее чем v0.8 на 8s).

## One-liner

v0.9: L3+ как v0.8, но **дешевле и быстрее** — 17 LLM requests
(vs 25), 144s (vs 388s), 13 tool calls (vs 20). Modeль создала
4 файла включая cli.py с багом (`click.group()` без `@`-декоратора)
и test_storage.py импортирует несуществующий storage.py. Machine
guards теперь **рано детектируют** проблемы и стопают: T001
failed на первой же задаче (всё ещё 0 commits — guard срабатывает,
но автоматически не правит). Legacy pack — те же рекорды что
v0.8 (9/9 + ✓1att + 3/3).

## По сравнению с v0.8.0

| Метрика | v0.8 | **v0.9** |
|---|---|---|
| reached_level | L3+ | L3+ = |
| LLM requests | 25 | **17** (-32%) |
| prompt_total | 202k | **111k** (-45%) |
| prompt_peak | 10.8k | **8.0k** (-26%) |
| tool_calls | 20 | **13** (-35%) |
| write_file | 11 | **4** (-64%) |
| shell_exec | 5 | **1** (-80%) |
| files on disk | 8 | 4 (тех. файлы) + cli.py + 2 test'а |
| commits | 0 | 0 = |
| stopped_reason | max_failures | task_not_done |
| status | 2 failed | **1 failed, 1 skipped** |
| wall_sec | 388 | **144** (-63%) |

**v0.9 в 2.6× быстрее и в 1.8× дешевле** при том же reached_level.
Это **прямой эффект machine guards**: ошибки детектируются рано
→ модель не успевает писать кучу мусора → run_plan стопает.

## Что нового в v0.9

Из git log v0.8.0..v0.9.0:
- **machine guards** — mkdir auto, empty-content detection,
  partial-progress label (commit 0b9b2e8)
- **AST empty-test detector** (a149ac6) — определяет `def test_x:
  pass` как пустой
- **lint pass** после каждой /go task'и (7266a09) — ruff с
  auto-fix
- **AST import-graph check** (2ac1c56) — проверяет что
  импортированные имена существуют

## Что произошло на T001

Модель сгенерировала:
1. `pyproject.toml` ✓
2. `setup.py` ✓ (with `entry_points={'console_scripts': ['notetool=notetool.cli:cli']}`)
3. `requirements.txt` ✓
4. `notetool/cli.py` — **с багом**:
   ```python
   click.group()  # ← пропущен `@`-декоратор!
   def cli(): pass
   ```
5. `tests/test_storage.py` — импортирует `notetool.storage.JsonStorage`,
   но **storage.py НЕ создан** → import error

Один shell_exec (pytest?) → код упал → T001 status=failed. T002
автоматически skipped (depends on T001).

## Что закрыл v0.9

Machine guards **повысили fail-fast** — модель не успевает писать
ерунду на 5+ файлов перед остановкой. Это:
- **дешевле** для пользователя (меньше токенов на мусор)
- **информативнее** (failed на конкретной T001 vs «max_failures»
  без понятного места)

## Что НЕ закрыл v0.9 для L4

**Всё ещё 0 commits.** Гипотеза была: «v0.9 machine guards могут
auto-commit'ить» — **не сбылась**. Machine guards проверяют
качество файлов (empty/lint/imports), но не дёргают `git add &&
git commit`. Модель должна это делать сама, и **всё ещё не
делает**.

## Архитектурный smell-check

v0.8 был **прорывом по объёму** (много write_file, много файлов).
v0.9 — **оптимизация цены**: тот же качественный уровень при
меньших ресурсах. Это типичная картина «релиза с guard'ами»:
не новые capabilities, а **дешевле и стабильнее**.

## Legacy probe pack v0.9.0 — стабилизация рекордов

| Probe | v0.7 | v0.8 | **v0.9** |
|---|---|---|---|
| `probe.py` | 8/9 | 9/9 | **9/9** = |
| `probe_code.py` | ✓ 1att | ✓ 1att | **✓ 1att** = |
| `probe_recipes.py` | 2/3 | 3/3 | **3/3** = |

Все рекорды **удержаны**. probe.py — 9/9 (полная корректность
ask-режима), probe_code — fix calc.add с первой попытки,
probe_recipes — все 3 recipe-сценария.

То есть v0.9 — **закрепление прорыва v0.8** на дополнительной
оси: легче, быстрее, дешевле при том же качестве. Это нормальный
полу-шаг после крупного landing'а v0.8.

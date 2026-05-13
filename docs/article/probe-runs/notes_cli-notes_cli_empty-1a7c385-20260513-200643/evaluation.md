# Evaluation: notes_cli × v0.11.0 — ReviewedAuto + recovery recipes

## Reached level: **L3** (= v0.10, повторение регресса)

ReviewedAuto fork mechanics ортогонален notes_cli. Live probe
**идентичен** v0.10 (4 LLM requests, 80s, 0 write_file). Но
legacy **починился**: probe_recipes 2/3 → 3/3.

## One-liner

v0.11: L3, тот же регресс что v0.10 — T001 «Проанализировать
текущую структуру», T002 «Определить архитектурные решения»,
T003 «Создать основной скрипт». Модель в code-mode дёрнула
project_map(), сказала «понятно, идём дальше» — 0 write_file.
**78 → 80s**, idem. Legacy: **probe_recipes recovery 2/3 → 3/3** и
**probe_fork_reviewer 3/3 NEW**.

## По сравнению с v0.10.0

| Метрика | v0.10 | **v0.11** |
|---|---|---|
| reached_level | L3 | L3 = |
| LLM requests | 4 | 4 = |
| prompt_total | 20k | 20k = |
| tool_calls | 4 | 4 = |
| write_file | 0 | 0 = |
| commits | 0 | 0 = |
| wall_sec | 78 | 80 = |

**Полная воспроизводимость регресса**. Тот же plan-mode паттерн:
T001 «Проанализировать», annotate_plan только добавляет Skills,
не переписывает Goal/Files. Это **не флуктуация temperature** —
это **системное свойство v0.10+ цепочки**.

## Что нового в v0.11

Из git log v0.10.0..v0.11.0:
- **ReviewedAuto fork** — режим где fork автоматически review'ится
  перед merge'ом
- **probe_fork_reviewer.py** появился в legacy (3/3 ✓ работает)
- Recovery probe_recipes — где-то поправили лежащую recipe-задачу

Все эти изменения **не влияют** на «спроектируй CLI» live-сценарий.

## Что закрепил v0.11

Recovery probe_recipes **подтверждает гипотезу из v0.10**: 2/3
на v0.10 был побочным эффектом fork-инфраструктуры (что-то
сломалось в общей цепочке). На v0.11 эту ось почистили → 3/3
возвращён.

При этом **live-регресс остался**. Значит причина live-регресса
**другая** чем причина recipes-регресса. Гипотеза:
- recipes-регресс v0.10 — конкретный prompt/код в recipes.py
  → починили в v0.11
- live-регресс v0.10+ — non-determinism plan-mode при той же
  системной prompt-цепочке. Возможно температура или какой-то
  переключатель в _PLAN_MODE_ADDENDUM поменялся → annotate_plan
  стал слабее перезаписывать «анализ» задачи в action-форму

## Архитектурный smell-check

v0.11 — **точно повторяющий регресс v0.10**, что подтверждает:
- регресс не флуктуация
- регресс не лечится без вмешательства в plan-mode цепочку
- regression-test через probe-suite **сработал бы** — мы бы
  увидели «v0.10 → v0.11: live no change, recipes recovered»

Этот run **усиливает** аргумент из v0.10 девлога: probe-suite
встроенный в CI **видит** регресс и **отделяет** «новые фичи
работают на узком тесте» от «смежные оси страдают».

## Legacy probe pack v0.11.0 — recovery recipes + новый axis

| Probe | v0.9 | v0.10 | **v0.11** |
|---|---|---|---|
| `probe.py` | 9/9 | 9/9 | **9/9** = |
| `probe_code.py` | ✓ 1att | ✓ 1att | **✓ 1att** = |
| `probe_recipes.py` | 3/3 | 2/3 | **3/3** ↑ (recovery) |
| `probe_forks.py` | — | 4/4 | **4/4** = |
| `probe_fork_reviewer.py` | — | — | **3/3** NEW |

probe_recipes вернулся к рекорду 3/3 (как v0.8/v0.9). Plus
**probe_fork_reviewer 3/3** впервые — ReviewedAuto fork
mechanism работает.

Итог v0.11: **fork-стек укрепился** (3 fork-проба сейчас, 2 из
3 в зелёном), recipes recovered. Live-регресс persists, требует
отдельной починки plan-mode.

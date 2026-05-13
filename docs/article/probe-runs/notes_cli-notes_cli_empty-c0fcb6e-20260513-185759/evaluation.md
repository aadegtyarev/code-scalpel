# Evaluation: notes_cli × v0.7.0 — первый прорыв в tools

## Reached level: **L3**

Тот же level что baseline {v0.3-v0.6}, но **впервые активность
tools**: 3 tool calls (vs 0 на baseline).

## One-liner

v0.7: первый прорыв в tools — annotate_plan ×2 + project_map ×1. run_plan ужесточился: stopped_reason=task_not_done вместо all_done. Files на диске всё ещё нет — L4 не достигнут.

## По сравнению с v0.6.0

| Метрика | v0.6 | **v0.7** |
|---|---|---|
| reached_level | L3 | L3 |
| user_turns | 1 | 1 |
| LLM requests | 10 | **4** |
| prompt tokens | 50k | **18k** |
| **tool_calls** | **0** | **3** (annotate_plan×2 + project_map×1) |
| stopped_reason | all_done | **task_not_done** |
| skipped | 7/7 | 1/7 (T001 не done, остановился) |
| files on disk | 0 | 0 |

## Главные изменения v0.6 → v0.7

1. **annotate_plan auto**: перед run_plan'ом автоматически
   крутится narrow_pass который дёргает project_map и обогащает
   TASKS.md. 2 вызова annotate_plan + 1 project_map в логах.
2. **task_not_done stopped_reason**: «fix: surface tool calls in
   run_plan and fix skipped classification» — run_plan теперь
   честно останавливается на первой skipped, не пробегает все 7.
3. **prompt tokens упали** — потому что run_plan не прошёл по
   всем 7 задачам (остановился на T001).

## Хорошо

- **Tool-loop наконец работает.** Модель впервые дёрнула
  project_map автоматически.
- **annotate_plan** — сильное улучшение plan-цепочки.
- **task_not_done** — честная семантика.

## Плохо

- Files **по-прежнему** не на диске. Модель **не дёрнула**
  write_file (хотя он есть с v0.7).
- L4 не достигнут — task_not_done сразу на T001.

## Архитектурный smell-check

**Это первая видимая точка прогресса** в нашей серии.
baseline-frame {v0.3-v0.6} был ровный L3 с 0 tools. v0.7 принёс:
1. Реальные tool calls (annotate_plan + project_map)
2. Честную классификацию run_plan'а
3. write_file в API — но **не в практике**

L4 (done) требует ещё одного звена — научения модели **писать**
через write_file. Это видимо v0.8+ или позже.

## Legacy probe pack v0.7.0

| Probe | v0.6 | **v0.7** |
|---|---|---|
| `probe.py` | 8/9 | **8/9** = |
| `probe_code.py` | ✓ 1att | **✓ 1att** = |
| `probe_recipes.py` | 2/3 | **2/3** = |

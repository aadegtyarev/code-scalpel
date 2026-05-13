# Evaluation: notes_cli × v0.3.0 (baseline)

## Reached level: **L3**

Plan-pipeline работает с MVP. Code-mode ещё не учит модель.

## One-liner

v0.3 baseline: L1+L2+L3 ✓ (план / TASKS.md в DSL / go запустился). L4 ✗ — на v0.3 нет `_CODE_MODE_ADDENDUM`, модель в run_plan task'е не получает инструкции «делать через write_file» и не справляется по плану.

## Главный пересмотр

**Раньше** я писал «модель не эмитит SR-блоки, поэтому 0/6 done».
**Правильно**: системник на v0.3 **не учит модель SR-формату** —
ни в общем `_SYSTEM_PROMPT`, ни в каком-либо mode_addendum. Только
`_PLAN_MODE_ADDENDUM` есть, и он явно говорит «NO SEARCH/REPLACE
blocks» (для plan mode).

В **code mode на v0.3 системник вообще ничему не учит** — нет
`_CODE_MODE_ADDENDUM`. Модель получает общий `_SYSTEM_PROMPT` про
tools (project_map, grep, read_file) и navigation. Ожидать что
она сама догадается до SR-формата — наивно.

Поэтому 0/6 done на v0.3 — **строго ожидаемое** поведение, не
регрессия.

## Trajectory

- **Step 1 (plan)**: `_PLAN_MODE_ADDENDUM` сработал. Reply 4.5k
  chars с 6 задачами в правильном DSL. `_maybe_save_plan` авто-
  сохранил TASKS.md. **L1+L2 reached**.
- **Step 2 (probe go)**: run_plan по 6 задачам. 8 LLM-запросов
  в `code_with_retry`. Модель в каждом task'е получала task-prompt
  без code-mode инструкций → отвечала «как делать словами» →
  skipped. **all_done, 0/6 done. L3 reached.**

## Метрики

| | значение |
|---|---|
| user_turns | 1 (только plan-step) |
| LLM requests | 9 |
| prompt_tokens_total | 44k (**сумма** по 9 запросам) |
| prompt_tokens_peak | 6.8k (один запрос, в 16k context — норма) |
| tool_calls_total | **0** |
| commits_landed | 0 |
| wall_time_sec | 198 |

## Adaptations

Из современного API доступно: `Runtime` базовый, `agent.ask`,
`code_with_retry`, `run_plan` — все без поздних kwargs (нет
`on_tool_executed`, `force_loop`, `fork_resolver`, `upstream`).

## Архитектурный smell-check

baseline для серии. **Plan-pipeline ✓ с MVP** — это **сильный**
результат. План-цепочка `plan addendum + _maybe_save_plan +
run_plan` работает с самого первого тэга проекта.

**Code-pipeline на v0.3 не достроен** — нет инструкции модели
что делать в code mode. Это **ожидание** для v0.7 где landed
`_CODE_MODE_ADDENDUM` (через `prompts/mode_code.md`).

## Legacy probe pack v0.3.0

| Probe | Result |
|---|---|
| `probe.py` | 8/9 |
| `probe_code.py` | ✗ 3att red (variance — другой прогон давал ✓; calc.add fix через SR нестабилен) |
| остальные | skipped — не существуют в `scripts/` на v0.3 |

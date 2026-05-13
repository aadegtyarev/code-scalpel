# Evaluation: notes_cli × v0.3.0 (baseline, plan→go)

## Reached level: **L3**

Plan-mode сработал, TASKS.md сохранён в DSL, `/go` (run_plan)
запустился и прошёл по всем 6 задачам. **Но ни одна не done** —
все skipped (модель не эмитила SR в run_plan turn'ах).

## One-liner

v0.3 baseline через правильный plan→go: TASKS.md 6 задач в DSL, run_plan прошёл all_done но 0/6 completed — модель в code-flow не пишет SR-блоки. 44k tokens, 0 tools, 0 commits.

## Trajectory

- **Step 1 (plan mode)**: одна реплика «спроектируй CLI...»
  → reply 4.5k chars с 6 задачами в правильном DSL `## T001:`
  с полями Goal/Files/Acceptance/Test command. `_maybe_save_plan`
  автоматически сохранил `.code-scalpel/TASKS.md` (2766 байт).
  **L2 reached.**

- **Step 2 (probe go)**: `run_plan` пошёл по 6 задачам подряд
  через `code_with_retry`. 8 LLM-запросов внутри (по 1.3 на
  задачу — то есть retry-loop **не работал**, как и ожидалось
  без `iterative_patch_loop`).
  **stopped_reason: all_done**, **tasks_completed: 0**.
  Все 6 задач имеют статус `skipped` — `_classify_outcome`
  ставит skipped когда модель эмитила reply **без SR-блоков**.
  **L3 reached, L4 нет.**

## Метрики

| Метрика | Значение |
|---|---|
| user_turns | 1 (один plan-step) |
| agent_llm_requests | 9 (1 plan + 6 task'ов + 2 annotate?) |
| prompt_tokens_total | 44k |
| completion_tokens_total | 3k |
| tool_calls_total | **0** |
| commits_landed | **0** |
| wall_time | 198 сек ≈ 3.3 мин |
| reached_level | **L3** |

## Adaptations (что отсутствует на v0.3)

| Что упало | Что значит |
|---|---|
| `Runtime.upstream_profile` | upstream-API не существует |
| `runtime.fork_resolver_missing` | Runtime не имеет атрибута (с v0.10) |
| `code_with_retry.on_tool_executed_missing` | мы слепы по tools |
| `code_with_retry.force_loop_missing` | iterative loop без force |
| `run_plan.on_tool_executed_missing` | то же для run_plan |
| `run_plan.fork_resolver_missing` | fork API ещё не landed |

То есть из современного API доступно только: `Runtime` базовый,
`agent.ask(mode=...)`, `code_with_retry(mode=...)`, `run_plan()`
без kwargs.

## Хорошо

- **Plan mode РАБОТАЕТ на v0.3.** `_PLAN_MODE_ADDENDUM` уже учил
  модель DSL формату. TASKS.md сохраняется автоматически через
  `_maybe_save_plan`.
- **run_plan не упал.** Прошёл по всем 6 задачам, не упёрся в
  отсутствующие capabilities.
- **Compat-shim работает** — fork_resolver / on_tool_executed
  отброшены, run_plan вызвался без них.

## Плохо

- **0/6 done** — модель в code-flow не эмитит SR. Видимо:
  - системник `_CODE_MODE_ADDENDUM` на v0.3 ещё не учит SR
    (есть только `_PLAN_MODE_ADDENDUM`)
  - или модель в run_plan-контексте получает task как «implement»
    но не дёргает write_file (которого нет) и не пишет SR-блоки
- **Tools.jsonl пуст** — но это побочный эффект отсутствия
  on_tool_executed hook'а, мы слепы. Реально модель могла дёргать
  project_map (в reply я её сообщений не вижу детально).
- **0 commits** — да, скипы не комитятся.

## Гипотезы о причинах

- На v0.3 системник для **code mode** ещё не учит модель SR. Только
  `plan mode` имеет addendum. `code_with_retry` крутит обычный
  ask + парсит SR из reply, но модель в `mode=code` без addendum
  не пишет SR-блоков — это **тот самый разрыв** между
  «capability существует» (SR-парсер) и «системник учит модели
  ей пользоваться» (отсутствует на v0.3).
- Может быть нужен `--mode code` step **отдельно** для задач,
  не через run_plan? Но run_plan и есть тот пайплайн который мы
  тестируем.

## Архитектурный smell-check

Это **первая полная картина**:
- L1 (план словами) — да, всегда
- L2 (TASKS.md в DSL) — **получили!** Plan mode сработал на
  самом раннем тэге проекта. Это **сильное доказательство** что
  `_PLAN_MODE_ADDENDUM` + `_maybe_save_plan` — рабочий механизм
  с MVP.
- L3 (go запустился) — да, инфраструктурно run_plan работает с
  v0.3
- L4 (хотя бы 1 done) — **нет** на v0.3, нужен системник для
  code-mode

Эта точка — **отличный** baseline для сравнения с v0.5+ где
появится code-mode-addendum / SR pipeline учится правильно.

## Legacy probe pack v0.3.0

| Probe | Result |
|---|---|
| `probe.py` | 8/9 (один отказ — модель не дёргает project_map) |
| `probe_code.py` | ✗ 3 attempts red (variance с предыдущим прогоном где было ✓; calc.add fix через SR нестабилен) |
| остальные | skipped — не существуют в `scripts/` на v0.3 |

# Evaluation: notes_cli × v0.7.0 — переломный тэг

## Reached level: **L3**

Тот же level что baseline, **но качественно иначе**: впервые
landed `_CODE_MODE_ADDENDUM` (через `prompts/mode_code.md`),
впервые активность tools (3 calls vs 0 на baseline).

## One-liner

v0.7: переломный тэг — appeared `prompts/mode_code.md` с инструкцией «write_file, project_map, run_tests». Модель **впервые** дёрнула tools: annotate_plan ×2 + project_map ×1. Files на диск всё ещё нет — модель не довела до write_file на T001 «создать структуру».

## Главный пересмотр

**Раньше** считал что «модель должна писать SR в run_plan task'ах».
**Точно**: системник на v0.3-v0.6 **вообще не учит** модель
формату патчей. На v0.7 появился `prompts/mode_code.md` который
**явно учит write_file** (а не SR!) с checklist:

> 1. Orient — project_map().
> 2. Read — read_file.
> 3. **Write — modify with write_file**.
> 4. Test — run_tests.
> ...

То есть на v0.7 системник:
- Учит модели использовать **`write_file`** (не SR)
- Даёт пошаговый checklist
- Plan runner перед task'ом дёргает `annotate_plan` (новый
  narrow_pass) который обогащает TASKS.md

Это объясняет **почему именно на v0.7** появились 3 tool calls:
`_CODE_MODE_ADDENDUM` начал работать.

## По сравнению с v0.6.0

| Метрика | v0.6 | **v0.7** |
|---|---|---|
| reached_level | L3 | L3 (но качественно иначе) |
| LLM requests | 10 | **4** (run_plan стоп на T001) |
| prompt_total | 50k | **18k** |
| prompt_peak | 7.3k | 5.9k |
| **tool_calls** | **0** | **3** (annotate_plan×2 + project_map×1) |
| stopped_reason | all_done | **task_not_done** |
| skipped | 7/7 | 1 (T001) → стоп |
| files on disk | 0 | 0 |

## Что произошло

1. **`prompts/mode_code.md`** — новый файл с инструкциями для
   code mode. Учит **write_file** (не SR).
2. **`annotate_plan`** — auto narrow_pass перед run_plan'ом.
   Дёргает project_map, обогащает TASKS.md. Видим 2 вызова
   annotate_plan + 1 project_map в логах.
3. **task_not_done classification**: «fix: surface tool calls
   in run_plan and fix skipped classification» (видимо v0.7) —
   run_plan теперь честно останавливается на первой
   skipped task'е, не пробегает все 7.

## Почему 0 files на диске — рассогласование plan↔code

Гляну реально что модель ответила на T001. В chat.jsonl:

**T001 в TASKS.md** (сгенерировано в plan mode):
> ## T001: Проанализировать текущую структуру проекта
> Goal: Понять текущее состояние проекта и определить, какие
>   файлы уже существуют.
> Files: project_map()
> Acceptance:
> - Получен список всех файлов в проекте.
> - Определено наличие или отсутствие необходимых файлов.
> Test command: manual

**Ответ модели в run_plan-цикле**:
> «Текущая структура проекта включает только `pyproject.toml`
> и пустой каталог `tests`. Необходимые файлы `main.py`,
> `storage.py` отсутствуют. Давайте создадим эти файлы и
> начнем с основного скрипта приложения.»

То есть модель **правильно** выполнила «**проанализировать**»:
дёрнула project_map, описала состояние, готова перейти к
следующей задаче. **Это и есть выполнение T001.**

**Но `run_plan` помечает skipped** потому что `mode_code.md`
требует «Every task MUST end with at least one successful
`write_file` call» — а T001 «проанализировать» не требует
write_file по своей сути.

## Архитектурное рассогласование plan ↔ code

Это **более интересное** открытие чем «модель не умеет
write_file». На v0.7:
- `_PLAN_MODE_ADDENDUM` **не запрещает** исследовательские
  задачи. Модель сгенерировала T001 как «проанализировать» —
  валидно с точки зрения plan-mode.
- `mode_code.md` **требует write_file для каждой task**.
- Результат: код-mode не может удовлетворить task которую
  plan-mode разрешил создать.

**Гипотезы решения** (не делаем сейчас):
1. PLAN_MODE addendum должен запрещать «анализ»/«понять» как
  отдельные task'и — план должен состоять из **действий**.
2. run_plan может пропускать «анализ» task'и без штрафа.
3. annotate_plan должен **переписывать** «проанализировать»
  в «создать X, Y, Z» если в Files перечислены реальные пути.

## Архитектурный smell-check

**Это первая видимая точка прогресса** в серии после ровного
baseline'а {v0.3-v0.6}. v0.7 принёс:
1. `_CODE_MODE_ADDENDUM` → модель учится использовать tools
2. annotate_plan → обогащение плана project_map'ом
3. task_not_done → честная классификация

Что **ещё не закрыто** для L4:
- Модель должна **дойти до** write_file. Видимо нужен ещё один
  слой prompt-pressure или few-shot примеров в `mode_code.md`.
- T001 «создать структуру» неоднозначна — возможно нужны более
  явные task'и в TASKS.md (для этого и существует annotate_plan,
  но видимо его пресет не учит «делай write_file»).

## Legacy probe pack v0.7.0

| Probe | v0.6 | **v0.7** |
|---|---|---|
| `probe.py` | 8/9 | **8/9** = |
| `probe_code.py` | ✓ 1att | **✓ 1att** = |
| `probe_recipes.py` | 2/3 | **2/3** = |

Legacy стабилен. Прогресс на v0.7 виден **только** в нашем live
probe (тип сценария «создай проект с нуля»), не в узких legacy.
Это и есть **главная польза** широкого live-замера vs точечного
legacy.

# Evaluation: notes_cli × v0.8.0 — **главный прорыв серии**

## Reached level: **L3+** (близко к L4)

Модель **реально работала**: 11 write_file, 5 shell_exec, 8 файлов на диске. L4 не достигнут только потому что **0 commits** — модель не выполнила финальный `git commit` который требует `mode_code.md`.

## One-liner

v0.8: **прорыв** — 20 tool calls (vs 3 на v0.7), 11 write_file, 8 файлов с рабочим кодом. annotate_plan переписал TASKS.md действенно: T001 «Определение структуры» с реальными файлами (вместо «проанализировать» на v0.7). Не L4: 0 commits, status=failed.

## По сравнению с v0.7.0

| Метрика | v0.7 | **v0.8** |
|---|---|---|
| reached_level | L3 | **L3+** |
| LLM requests | 4 | **25** |
| prompt_total | 18k | 202k |
| prompt_peak | 5.9k | **10.8k** (max в серии) |
| **tool_calls** | 3 | **20** |
| write_file | 0 | **11** |
| shell_exec | 0 | **5** |
| files on disk | 0 | **8** |
| commits | 0 | 0 |
| stopped_reason | task_not_done | **max_failures** |
| status | 1 skipped | **2 failed** |

`status=failed` (не skipped) — **прогресс**: модель сделала patch, applier применил, но post-checker'ы (commit landed) не прошли.

## Что нового в v0.8

- **annotate_plan переписал TASKS.md осмысленнее**: T001 «Определение структуры проекта» с Files: pyproject.toml, setup.py, requirements.txt, notes_cli/__init__.py — **реальные пути для write_file** (vs v0.7 «проанализировать структуру»).
- **auto_load_skill** — новый tool call в v0.8.
- **shell_exec ×5** — модель пыталась запустить pytest.
- **11 write_file** — модель создала реальный код: pyproject.toml, setup.py, requirements.txt, notes_cli/__init__.py, notes_cli/cli.py, tests/__init__.py, tests/test_cli.py.

## Что не работает для L4

`mode_code.md` требует «8. Commit — at the END of every task, you MUST stage and commit». Модель **не закоммитила**. shell_exec×5 был pytest, не git commit. run_plan проверяет `git rev-parse HEAD` до/после task → failed.

## Качественный сдвиг

**v0.7 → v0.8 — главный watershed серии**:
- v0.7: появился `mode_code.md` → модель **поняла** про write_file, дёрнула project_map. Но T001 был «проанализировать» — не дошла до write_file.
- v0.8: annotate_plan **переписал** TASKS.md так что T001 стал действенным → модель **сделала** write_file ×11, создала весь проект.

Landing annotate_plan на v0.8 **закрыл цикл**: plan-mode генерирует исходный план → annotate_plan обогащает действенными task'ами → code-mode исполняет. Это видно **только в нашем probe**.

## Что осталось до L4

Один кусочек: модель должна делать `git commit` в конце task'и. mode_code.md уже просит это явно, но 14b игнорирует. Гипотезы:
- Маленькая модель забывает последний шаг checklist'а.
- Нужен post-write hook который автоматически commit'ит (v0.9 machine guards?).

## Архитектурный smell-check

Прогресс **скачкообразный**: v0.5 (code_with_retry) → v0.7 (mode_code.md) → v0.8 (annotate_plan). Каждый landing закрывает одно недостающее звено. v0.8 — первая реально продуктивная точка серии.

## Legacy probe pack v0.8.0 — **рекорды по всем осям**

| Probe | v0.6 | v0.7 | **v0.8** |
|---|---|---|---|
| `probe.py` | 8/9 | 8/9 | **9/9** ↑ (perfect, впервые) |
| `probe_code.py` | ✓ 1att | ✓ 1att | ✓ 1att = |
| `probe_recipes.py` | 2/3 | 2/3 | **3/3** ↑ (perfect, впервые) |

**Все доступные axes legacy показали либо рекорд, либо стабильность**. probe.py **впервые** дал 9/9 — модель ответила на все 9 базовых вопросов корректно (нет «не могу найти Session.py»). probe_recipes **впервые** 3/3 — все 3 recipe-сценария работают.

То есть v0.8 — это **полный watershed**: и live, и legacy одновременно показали качественный сдвиг. Главные landings v0.8:
- annotate_plan auto (action-oriented task'и)
- auto_load_skill (Skills: line → нужные skill загружаются перед task)
- narrow_pass framework как общая инфраструктура


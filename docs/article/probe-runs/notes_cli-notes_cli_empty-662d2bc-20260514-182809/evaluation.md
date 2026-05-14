# Evaluation: notes_cli × main (662d2bc) — L5, task_solved впервые

## Reached level: **L5** (all_done + pytest 5/5 на final_tree)

**Первый task_solved за всю историю проекта.** Acceptance v0.13
(≥1 task_solved на notes_cli) формально достигнут.

## Цифры

| Метрика | Значение |
|---|---|
| stopped_reason | **all_done** |
| tasks_completed | 8 of 9 (T006 skipped как опциональный) |
| LLM requests | 52 |
| prompt_tokens_total | 559k |
| tool_calls_total | 40 (annotate_plan=2, project_map=1, write_file=22, run_tests=13, shell_exec=1, auto_load_skill=1) |
| wall_sec | 444 |
| pytest на final_tree | **5 passed** |

## Что собрала модель

Файлы в final_tree:
- `notes.py` — основной CLI с argparse, add/list/search/delete
- `tests/test_notes.py` — 5 тестов на все команды
- `notes.json` — storage
- `setup.py`, `pyproject.toml`, `README.md`

Всё запускается, тесты идут зелёные. Это **рабочее CLI-приложение
для заметок**, написанное моделью end-to-end через probe-suite v2
без ручного вмешательства.

## Какие правки сделали это возможным (cumulative)

1. **PR #109 skip-without-stop** — T001 (analytic с
   `Files: project_map()`) больше не стопает план.
2. **PR #110 auto-commit hook** — модель никогда не делает
   финальный commit; pipeline делает за неё.
3. **PR #116 defer-not-fail** — task с no-op done (HEAD не
   двинулся, тесты зелёные) остаётся done, не failed.
4. **PR #120 quoted-manual fix** — `Test command: "manual"` (в
   кавычках) больше не запускается как pytest arg.

Каждая правка добавила примерно одну долю долголетия pipeline'у.
Сумма даёт L5.

## Дисперсия (N=3 после quoted fix)

| Run | tasks_completed | reached_level | stopped_reason |
|---|---|---|---|
| 1 (этот, 182809) | **8** | **L5** | all_done |
| 2 (183627) | 0 | L3 | max_failures (T001+T002 failed) |
| 3 (183920) | 0 | L3 | max_failures |

Один из трёх дотянул до task_solved. Воспроизводимость **низкая**,
но это **не нулевое значение**. До PR #120: 0/0/0 на N=3.
После: 1/3 — изменение есть.

## Открытые проблемы (для следующей итерации)

1. **Дисперсия sampler'а** — 2 из 3 прогонов падают на T001/T002.
   На run 3 T001 Files имел `notes_cli/` (directory) — verify может
   не находить если модель создала файлы под другим именем пакета
   (`notes/` vs `notes_cli/`). Mismatch имени директории в плане
   vs реальной структуре после первой write_file.

2. **Test изоляция** — на run 1 после quoted-fix модель **прошла**.
   На N=3 после defer-not-fail run 1 же был с похожей проблемой
   (test_add накапливал duplicates в `notes.json` между retries
   и тест fail'ил `assert len == 1`). Сейчас это не задело —
   sampler выбрал другой test layout. Но проблема **в pipeline'е
   не решена**.

3. **N≥10 для надёжной статистики** — N=3 слишком шумно. Нужно
   накопить выборку для honest claim про «% task_solved».

## Главный вывод

L5 на N=1/3 — **существенный прогресс**. Серия:
- pre-skip-without-stop: 0/11 на historical-серии
- post-#109/#110: 4/0/0 (L4, не L5)
- post-#116/#118/#119/#120: **8/0/0 (L5 впервые)**

Acceptance v0.13 достигнут. Дальше работа над **воспроизводимостью**
(consistency) — отдельная итерация.

Подробности — глава 39 девлога (если будем писать).

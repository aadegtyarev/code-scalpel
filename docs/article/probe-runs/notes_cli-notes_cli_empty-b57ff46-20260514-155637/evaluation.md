# Evaluation: notes_cli × main (b57ff46) после defer-not-fail — run 1

## Reached level: L3+ (1 done, T002)

После PR #116 (defer-not-fail). Метрики:

| | run 1 (этот) | pre-defer run 1 (eb5ee2f) |
|---|---|---|
| tasks_completed | 1 | 4 |
| LLM requests | 44 | 53 |
| prompt_tokens_total | 461k | 596k |
| tool_calls_total | 43 | 37 |
| write_file | 22 | 23 |
| wall_sec | 287 | 563 |

Стохастика sampler'а: на этом прогоне модель **не дошла** до того
красивого 4-done сценария.

## Что показал прогон

- T001 → skipped (`Files: project_map()`, как обычно) → skip-without-stop пропустил.
- T002 → done (создание notes/__init__.py, cli.py, tests/test_notes.py).
- **T003 → failed**, T004 → failed → max_failures (2 consecutive).
- **НО**: на `final_tree` запуск `pytest tests/test_notes.py` показывает **3 passed**. То есть код **в конце** работает.

## Главная находка — verify-timing блокер

В `tools.jsonl` видно очевидный **debug-loop модели** на T003:
- write_file `tests/test_notes.py` → `\n` (обнулила)
- write_file `notes/cli.py` → `\n` (обнулила)
- read_file → write_file (короткая версия) → run_tests → upadte → re-write_file → run_tests …

22 write_file подряд на двух файлах. Модель пыталась стабилизировать
тест, но pipeline в какой-то момент посередине запустил
`_verify_task_test_command` (`pytest tests/test_notes.py`) — на тот
момент **тесты были невалидны** → outcome failed → переклассификация.
**defer-not-fail не сработал** (он работает только когда `head_after ==
head_before` после auto-commit hook'а, т.е. для no-op done; здесь
HEAD сдвинулся, но verify failed).

То есть текущий блокер — **timing**: pipeline отбраковывает task в
момент когда модель ещё **в процессе** дописывания, и **никогда не
переоценивает** failed task'и после.

## Гипотеза для следующей правки

**Re-verify failed на done**: после каждого успешного done task'а
перепроверить failed task'и сверху по списку. Если их Files
существуют и Test command зелёный — переклассифицировать в done.
Это естественно для случая «T003 fails на verify в середине
debug-loop'а, T004 завершает работу и тесты теперь зелёные».

Альтернатива: **debug_pass** (уже есть в config, off by default).
Дать модели ещё 1-2 попытки прямо в T003 с hint'ом теста-fail'а.
Менее естественно, но не требует rewriting plan-loop'а.

## Главный вывод

Один done из семи. **Меньше** чем пред-defer run 1 (4 done) — это
**не значит** что defer-not-fail плох, это значит что sampler в
этой сессии лёг хуже. И блокер L4→L5 не дефер-related, а
verify-timing. Ждём больше прогонов для honest mean.

# Evaluation: notes_cli × main (eb5ee2f) — L4 впервые достигнут

## Reached level: **L4** (partial — 4/7 tasks done)

**Впервые за всю серию (12 historical-прогонов на v0.3 → main).**
На всех предыдущих — `tasks_completed: 0`. Здесь — 4 task'и
закрыты, 4 коммита от auto-commit hook'а, pytest на final_tree
зелёный (6/6).

## One-liner

main: 4 done из 7 (T002-T005), pytest 6/6. Все 4 коммита от
`auto-commit hook` — модель сама ни одного commit'а не сделала.
Skip-without-stop пропустил T001 (Files: project_map() — analytic
без real files). T006/T007 failed: модель не написала новый код
(тесты уже были в T005), HEAD не двинулся, hook не помог. Это
первый L4 в проекте — landed PR #109 (skip) + PR #110 (auto-commit)
работают **в комбинации**.

## Прогон в цифрах

| Метрика | main run 1 | v0.8 (best historical) |
|---|---|---|
| reached_level | **L4** | L3+ |
| tasks_completed | **4** | 0 |
| LLM requests | 53 | 25 |
| prompt_tokens_total | 596k | 202k |
| tool_calls_total | 37 | 20 |
| write_file | 23 | 11 |
| commits_landed | **4** | 0 |
| wall_sec | 563 | 236 |

Прогон в 2.5× дороже v0.8 по токенам, но **впервые** доводит
задачу до auto-committed состояния.

## Что произошло пошагово

1. **Plan-turn**: модель выдала T001-T007. T001: «Проанализировать
   существующую структуру» с `Files: project_map()` (analytic).
   T002: создать notes/ tests/. T003-T005: notes.py + storage.py +
   интеграция. T006-T007: тесты.

2. **TASKS.md сохранён** на диск (`.workdir/.code-scalpel/TASKS.md`).
   annotate_plan добавил `Skills: python` ко всем task'ам.

3. **T001 → skipped**: модель в code mode ответила «структура такая
   и такая» текстом, без write_file. `_classify_outcome` →
   `skipped`. Раньше (до PR #109) → break. Теперь → continue к T002.

4. **T002 → done**: модель сделала write_file для `notes/__init__.py`,
   `tests/__init__.py`, `pyproject.toml`. HEAD не двинулся (модель
   не сделала commit). **`auto_commit_on_done` сработал**:
   `git add -A && git commit -m "T002: Создать структуру для заметок"`
   → HEAD сдвинулся → status остался `done`.

5. **T003 → done**: `notes/notes.py` с функциями add/list/search/delete.
   Аналогичный путь через auto-commit hook.

6. **T004 → done**: `notes/storage.py` с save/load в JSON.
   Auto-commit hook.

7. **T005 → done**: интеграция (notes.py использует storage.py).
   Test command: `pytest tests/` запустился через
   `_verify_task_test_command` — pytest зелёный → ok.
   Auto-commit hook.

8. **T006 → failed**: тесты для notes.py. Модель ответила, что тесты
   уже написаны в T005 (правда — `test_notes.py` уже на диске).
   Нет write_file → HEAD не двинулся → auto-commit hook
   попытался `git add -A`, но **нечего staged** → commit не прошёл
   → status переклассифицирован в `failed`.

9. **T007 → failed**: симметрично T006 для test_storage.py.

10. **stopped_reason: max_failures** (2 consecutive failed).

## Что показал прогон

**Положительное** (доказательство эффекта landed PR):
- PR #109 (skip-without-stop) — T001 skipped не остановил план,
  pipeline дошёл до T002.
- PR #110 (auto-commit hook) — **все 4 done-таска получили коммит
  от hook'а**. Модель ни разу не сделала commit самостоятельно
  (как и предсказано в reality-разборе главы 36). Без hook'а
  все 4 task'а переклассифицировались бы в failed.
- Pytest на final_tree зелёный (`6 passed`). Код реально работает.

**Отрицательное** (что не закрыто):
- L5 (`all_done`) не достигнут — 4/7, на T006-T007 модель не
  сделала ничего нового и они упали через auto-commit hook
  (нечего staged).
- T001 фейл, потому что модель в plan-mode иногда выдаёт
  analytic-task'у с `Files: project_map()`. На прогоне 2 это же
  поведение приводило к skipped → break (после 2 подряд skipped).
- Семантика «task уже сделан в предыдущей» (T006 повторяет
  test_notes.py из T005) не разруливается — pipeline считает её
  failed.

## Сравнение с прогонами 2 и 3 (N=3)

| | Run 1 (152318) | Run 2 (153300) | Run 3 (153536) |
|---|---|---|---|
| tasks_completed | **4** | 1 | 0 |
| commits_landed | 4 | 1 | 0 |
| reached_level | L4 | L3+ | L3 |
| stopped_reason | max_failures | task_not_done (2 skipped) | max_failures |
| prompt_tokens | 596k | 206k | 195k |

**Дисперсия большая.** Среднее ~1.67 done на прогон. Но **2 из 3
прогонов имели хотя бы 1 done** — раньше (в 11 historical)
было **0 из 11**. То есть landed правки **смещают распределение**,
даже если каждый отдельный прогон стохастичен.

Для уверенной воспроизводимости (≥1 done на 9 из 10 прогонов)
нужны дополнительные правки — главные кандидаты:

1. **T001-rewriter** — если модель выдаёт `Files: project_map()`,
   pipeline должен это распознать и попросить модель переписать
   T001 в action-form (либо удалить task'у вовсе). Сейчас skip
   спасает, но это не идеально — на прогоне 2 первый skip привёл
   к двум подряд skipped → стоп.
2. **Defer-not-fail для "task уже сделан"** — T006/T007 при попытке
   повторить уже сделанное должны быть `done` (без коммита, raise
   `noop_done` status) или `skipped`, не `failed`. Сейчас они
   ловят 2 подряд failed → max_failures.
3. **Tests-on-empty-checked** — если test command `pytest` на T6/T7
   запустится и пройдёт (тесты уже на диске и зелёные), можно
   считать task done без HEAD-advance.

## Главный вывод

**Это первый L4 в проекте.** За всю historical-серию (11 прогонов
на v0.3 → main) такого не было. Главное доказательство — на main
прогон 1 показал что pipeline **может довести задачу до done +
auto-commit**, причём в *production-quality виде* (pytest зелёный,
4 коммита с осмысленными message'ами).

L5 (полный план + pytest) пока нигде. До него нужны ещё 2-3
правки (см. список выше). Acceptance v0.13 (≥1 task_solved) —
**формально не достигнут** (`verdict: user_gave_up` потому что
не L5), но **сущностно достигнут**: pipeline впервые делает
полезную работу и закрывает её коммитами.

Это поворотный момент серии. Подробности — глава 39 девлога.

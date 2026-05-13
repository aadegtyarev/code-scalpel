# Probe runs — index

Реестр всех прогонов probe-suite v2. Обновляется автоматически
после каждого `probe finalize`. Поиск через `grep`:

```bash
grep "fix_bug" INDEX.md      # все фикс-бага прогоны
grep "v0.10" INDEX.md         # все прогоны на версии v0.10.x
grep "user_gave_up" INDEX.md  # все где сдался
grep "retry" INDEX.md         # все где упоминается retry в one-liner
```

Что значат столбцы:

| Столбец | Что |
|---|---|
| `run-id` | `<scenario>-<project>-<sha>-<YYYYMMDD-HHMMSS>` |
| `date` | ISO день когда стартовал |
| `scenario` | `a_diag_plan` / `b_spec_plan` / `c_fix_bug` / `d_new_feature` |
| `project` | `mini_cli` / `mini_cli_with_bug` / `mini_fullstack` |
| `commit` | `[sha7](github-url)` чтобы откатиться и переиграть; `⚠️dirty` если репо был грязный |
| `verdict` | reason финализации: `task_solved` / `user_gave_up` / `error` |
| `turns` | сколько turn'ов сделал юзер (я) |
| `tokens` | суммарно prompt+completion, тысячами (`12k`) |
| `one-liner` | одна фраза из evaluation.md `One-liner` секции |

## Стратегия historical-серии

**От старого к новому**, baseline = v0.3.0. Сравниваем всегда
**новые прогоны со старыми**, не наоборот.

**Общая ось:** `a_diag_plan` (планирование) на **всех** версиях
начиная с v0.3 — это даёт чистую кривую «как меняется качество
планирования от MVP к main». Другие сценарии добавляются по
capabilities-матрице:
- v0.5+ → + `c_fix_bug` (с появлением code_with_retry)
- v0.6+ → + `d_new_feature` (с появлением write_file)
- v0.10+ → + swap-тесты (с появлением Fork API)

## Таблица прогонов

| run-id | date | scenario | project | commit | verdict | turns | tokens | one-liner |
|---|---|---|---|---|---|---|---|---|
| `a_diag_plan-mini_cli-9d9ba4f-20260513-162209` | 2026-05-13 | a_diag_plan | mini_cli | [`9d9ba4f`](https://github.com/aadegtyarev/code-scalpel/commit/9d9ba4fc452fd168d8af7f9946b662c4a6a3f216) ⚠️dirty | error | 2 | 24k | _(нет one-liner)_ |

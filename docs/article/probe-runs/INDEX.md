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
| _(пока пусто — historical-серия ещё не запущена)_ | | | | | | | | |
| `notes_cli-notes_cli_empty-9d9ba4f-20260513-164542` | 2026-05-13 | notes_cli | notes_cli_empty | [`9d9ba4f`](https://github.com/aadegtyarev/code-scalpel/commit/9d9ba4fc452fd168d8af7f9946b662c4a6a3f216) ⚠️dirty | user_gave_up | 3 | 13k | _(нет one-liner)_ |
| `notes_cli-notes_cli_empty-5f09a0d-20260513-165724` | 2026-05-13 | notes_cli | notes_cli_empty | [`5f09a0d`](https://github.com/aadegtyarev/code-scalpel/commit/5f09a0d1749c193196b583054ad5c41176af1cdd) ⚠️dirty | user_gave_up | 2 | 10k | _(нет one-liner)_ |
| `notes_cli-notes_cli_empty-a91c68d-20260513-170631` | 2026-05-13 | notes_cli | notes_cli_empty | [`a91c68d`](https://github.com/aadegtyarev/code-scalpel/commit/a91c68d72e1e7e94f1a08568904f0b64b9ff6de9) ⚠️dirty | user_gave_up | 2 | 10k | _(нет one-liner)_ |
| `notes_cli-notes_cli_empty-767e02b-20260513-171624` | 2026-05-13 | notes_cli | notes_cli_empty | [`767e02b`](https://github.com/aadegtyarev/code-scalpel/commit/767e02b821cd15567e345911b1794517e4ffcebe) ⚠️dirty | user_gave_up | 2 | 11k | _(нет one-liner)_ |
| `notes_cli-notes_cli_empty-c0fcb6e-20260513-172853` | 2026-05-13 | notes_cli | notes_cli_empty | [`c0fcb6e`](https://github.com/aadegtyarev/code-scalpel/commit/c0fcb6eae7d2d3c9d6a351e427f321a1eb7c1b6d) ⚠️dirty | user_gave_up | 2 | 12k | _(нет one-liner)_ |
| `notes_cli-notes_cli_empty-d6e9c37-20260513-173951` | 2026-05-13 | notes_cli | notes_cli_empty | [`d6e9c37`](https://github.com/aadegtyarev/code-scalpel/commit/d6e9c377be14ae8c72eeffd4c199cd25b7cdfe21) ⚠️dirty | user_gave_up | 2 | 13k | _(нет one-liner)_ |

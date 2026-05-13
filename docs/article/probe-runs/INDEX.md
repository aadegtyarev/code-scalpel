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

## Таблица прогонов

| run-id | date | scenario | project | commit | verdict | turns | tokens | one-liner |
|---|---|---|---|---|---|---|---|---|
| `c_fix_bug-mini_cli_with_bug-ad51ab8-20260513-144155` | 2026-05-13 | c_fix_bug | mini_cli_with_bug | [`ad51ab8`](https://github.com/aadegtyarev/code-scalpel/commit/ad51ab87bca083ea087ace2c64499c6a1bd4ef7f) | user_gave_up | 3 | 144k | _(нет one-liner)_ |

Дополнительные срезы по версиям / capabilities-матрица —
появятся когда соберём 5+ прогонов (см. `scripts/probes_v2/PROTOCOL.md`,
секция «История»).
| `a_diag_plan-mini_cli-bca504e-20260513-145240` | 2026-05-13 | a_diag_plan | mini_cli | [`bca504e`](https://github.com/aadegtyarev/code-scalpel/commit/bca504e014603de1bb8f0ac9e6b48fd5d6b99ca5) ⚠️dirty | task_solved | 3 | 26k | _(нет one-liner)_ |
| `c_fix_bug-mini_cli_with_bug-00916ae-20260513-145908` | 2026-05-13 | c_fix_bug | mini_cli_with_bug | [`00916ae`](https://github.com/aadegtyarev/code-scalpel/commit/00916ae070210a4466cbe5be61ab05e76e35e0e6) ⚠️dirty | error | 1 | 31k | _(нет one-liner)_ |
| `c_fix_bug-mini_cli_with_bug-450cf87-20260513-153012` | 2026-05-13 | c_fix_bug | mini_cli_with_bug | [`450cf87`](https://github.com/aadegtyarev/code-scalpel/commit/450cf876293e7f56af433cea78c1d780c92b4cba) | user_gave_up | 2 | 87k | _(нет one-liner)_ |
| `c_fix_bug-mini_cli_with_bug-a392a2e-20260513-160019` | 2026-05-13 | c_fix_bug | mini_cli_with_bug | [`a392a2e`](https://github.com/aadegtyarev/code-scalpel/commit/a392a2ec8c1d641bbd112679bb34a79ea6e8aa2f) | user_gave_up | 2 | 205k | _(нет one-liner)_ |

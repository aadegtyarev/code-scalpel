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
| `version` | `v0.X.Y` или `main_<sha>` |
| `verdict` | `pass_score/pass_max` + reason: `task_solved` / `user_gave_up` / `error` |
| `turns` | сколько turn'ов сделал юзер (я) |
| `tokens` | суммарно prompt+completion, тысячами (`12k`) |
| `one-liner` | одна фраза из evaluation.md `One-liner` секции |

## Таблица прогонов

| run-id | date | scenario | project | version | verdict | turns | tokens | one-liner |
|---|---|---|---|---|---|---|---|---|
| _(пока пусто — первый прогон ещё не сделан)_ | | | | | | | | |

Дополнительные срезы по версиям / capabilities-матрица —
появятся когда соберём 5+ прогонов (см. `scripts/probes_v2/PROTOCOL.md`,
секция «История»).

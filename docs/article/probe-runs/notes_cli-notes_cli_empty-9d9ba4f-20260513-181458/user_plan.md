# User plan: notes_cli × v0.3.0 (baseline)

Первая точка historical-серии по **правильному workflow** plan→go.

См. `scripts/probes_v2/scenarios/notes_cli.md` + `HISTORICAL_PLAYBOOK.md`.

Ожидание: на v0.3 нет write_file → run_plan на задачах создания
файлов может либо обходиться через SR с пустым SEARCH, либо
застрять. `iterative_patch_loop=False` по умолчанию, `force_loop`
kwarg ещё отсутствует → compat-shim отбросит → одношаговое
выполнение задач без retry.

Reached level — увидим в процессе.

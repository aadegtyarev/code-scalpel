# Evaluation: notes_cli × v0.6.0 (rename /run → /go + REVIEW addendum)

## Reached level: **L3** (= baseline)

Появился `_REVIEW_MODE_ADDENDUM`, но **`_CODE_MODE_ADDENDUM` всё
ещё нет** — нашу задачу это не сдвинуло.

## One-liner

v0.6: L3 как baseline. `_REVIEW_MODE_ADDENDUM` появился (mode_addenda 2→4 если считать оба), но code-mode инструкции для модели всё ещё нет. probe.py восстановился до 8/9 после v0.5 регрессии.

## Главный пересмотр

**Раньше** писал: «prompt_tokens вырос с ~8k до 50k. Видимо в
v0.6 системник существенно длиннее».
**Точно**: `prompt_tokens_total=50k` — **сумма** по 10
round-trips, не размер одного запроса. `prompt_peak=7.3k` (это
макс одного запроса) — в норме (< 16k context limit). Сравнивать
длину системника надо через **peak**, не total.

v0.6 peak (7.3k) ≈ v0.4 peak (6.6k) — системник особо не вырос.
Что выросло — количество запросов (run_plan пробежал все 7
задач, ни одна не сорвалась как done, all_done с 0 commits).

## По сравнению с v0.5.0

| Метрика | v0.5 | v0.6 |
|---|---|---|
| reached_level | L3 | L3 = |
| LLM requests | 13 | 10 (-3) |
| prompt_total | 79k | 50k (-37%) |
| prompt_peak | 9.4k | 7.3k (-22%) |
| tool_calls | 0 | 0 |
| skipped | 7/7 | 7/7 |
| wall_sec | 186 | 162 |

v0.6 **дешевле** v0.5 при том же результате. Системник немного
ужался (peak ↓). Один из режимов из v0.5 откатили или
переработали.

## Legacy probe pack v0.6.0 — recovery

| Probe | v0.3 | v0.4 | v0.5 | **v0.6** |
|---|---|---|---|---|
| `probe.py` | 8/9 | 8/9 | 6/9 ↓ | **8/9** ↑ recovery |
| `probe_code.py` | ✗ 3att | ✗ 3att | ✓ 1att | **✓ 1att** = |
| `probe_recipes.py` | — | — | 2/3 | 2/3 = |

`probe.py` вернулся к baseline 8/9. `probe_code` стабильно
зелёный. v0.5 был единственной точкой с регрессией basic ask —
v0.6 исправил.

## Архитектурный smell-check

Третья стабильная L3 точка (после v0.3 и v0.4). v0.5 был
переходным с регрессией. v0.6 — стабилизация и cleanup.

**Главное** ожидание серии теперь полностью на v0.7 — landing
write_file + project_map + `_CODE_MODE_ADDENDUM` (через
`prompts/mode_code.md`). Это **первый** тэг с code-mode
инструкцией для модели.

# User plan: notes_cli × v0.3.0 (historical baseline)

## Что я хочу добиться

**Первая точка historical-серии** (методология «одна задача,
разный объём»). Используем `scenarios/notes_cli.md` — базовая
задача про CLI для заметок. Реплики — те же что будут на всех
последующих тэгах, для сопоставимости.

Ожидаю на v0.3.0:
- Tool-loop слабый → возможно scalpel вообще не дёрнет project_map
- Нет write_file → файлы появятся только если модель эмитит SR
- Reached level скорее всего L1 (план словами) или L2 (план + SR-блоки)

## Стиль

`user_tone_of_voice.md`. Реплики — минимальные, по reference-таблице
в `scenarios/notes_cli.md`.

## Базовая реплика (turn 1)

> хочу собрать python-CLI для заметок: команды add, list, search, delete. json-storage, pytest. спроектируй и реализуй с тестами. если есть архитектурные вопросы — задай.

mode: `ask` (на v0.3 ask тянет — в коде scalpel'а это базовый
режим).

## Критерии остановки

- task_solved: reached L5+ (TASKS.md /go прошёл)
- partial: reached L1-L4
- user_gave_up: семантическая петля или >15 turn'ов без прогресса
- error: инфраструктура

## Что НЕ говорю

См. `scenarios/notes_cli.md` — не диктую имена / структуру /
библиотеки.

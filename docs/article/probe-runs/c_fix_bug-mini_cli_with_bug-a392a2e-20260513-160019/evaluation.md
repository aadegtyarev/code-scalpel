# Evaluation: c_fix_bug-mini_cli_with_bug-a392a2e-20260513-160019

## One-liner

Mode-фикс не спас: code_with_retry дёргает 14b через write_file overwrite — 3 retry усугубили поломку до пустого core.py. **Главная проблема не в режиме, а в `write_file content=<полный файл>` на сложных классах.** 200k tokens, 0 commits.

## Trajectory

- **Turn 1 (ask)**: 5 read_file + 1 run_tests + 1 project_map. Чёткая диагностика. **Ноль write_file**, как и должно быть в ask. Это **главное достижение mode-фикса** — turn 1 теперь делает то что должен.
- **Turn 2 (code)**: code_with_retry → 3 write_file подряд. Каждый раз 14b генерирует полный новый файл через `write_file(path, content=...)` — то же самое что в чистом ask режиме. iterative_patch_loop добавил retry но **не сменил формат**: write_file overwrite остался. Результат — core.py разваливается с каждым retry, в конце содержит только `mark_done` без класса.

После 3-го retry семантическая петля: «Извините за путаницу. Давай исправим...» повторяется **6 раз подряд** в одном reply без новых tool calls.

## Сравнение с #1 (то же сценарий в чистом ask)

| Метрика | #1 (ask only) | #1' (ask + code) |
|---|---|---|
| user_turns | 3 | 2 |
| LLM requests | 18 | **24** (+33%) |
| prompt tokens | 140k | **202k** (+44%) |
| write_file count | 3 | 3 |
| commits | 0 | 0 |
| Поломал core.py | да | да (хуже — методы класса полностью вне) |

**Mode-workflow ХУЖЕ по трудозатратам** — больше LLM-запросов, больше токенов. Code mode iterative loop пытается чинить, но 14b в новом retry опять делает write_file целиком → loop усугубляет.

## Главный вывод

`mode=code` сам по себе **не решает проблему** поломки структуры файла. Iterative patch loop у нас архитектурно прямой: «модель пишет → tool применяет → тесты → retry». Если **модель в каждом retry выбирает write_file целиком**, цикл превращается в катастрофу.

Корень — в **выборе формата патча 14b**:
- SEARCH/REPLACE даёт 23/24 на 24-test бенче (глава 5 девлога) — это **точечные edit'ы**
- write_file через native function call даёт переписывание целиком

14b на нашем стеке **предпочитает write_file** для multi-line изменений. Это видно по 3 write_file без единого SR-edit в reply.

## Гипотезы о причинах

1. **Системник толкает к write_file**. У нас `prompts/system.md` упоминает write_file как «способ создания/обновления файлов» — модель его выбирает приоритетом.
2. **Native function call формат поощряет write_file** vs SR в reply: tool_call'и формализованы JSON-schema, а SR — это «свободный текст с маркерами», менее структурно.
3. **14b на сложных файлах** не справляется с воспроизведением структуры построчно — теряет отступы класса, декораторы, docstring'и.

## Как теоретически можно было бы лечить

(Не делаю сейчас — это диагностика.)

1. **Запретить write_file overwrite на существующие .py файлы** — hard guard. Только range mode (`start_line`/`end_line`) или create new file. Это force'ит модель использовать SR или range-patch. Записать в plan.md.
2. **Post-write `py_compile`** валидация (уже было в evaluation #1) — отказывать в write если синтаксис битый. Откатывать.
3. **Few-shot SR-edit в системнике** — показать 14b что для одной функции используется SR, не write_file.
4. **Anti-loop**: 2 неудачных write_file подряд → стоп цикла, escalate. У нас есть `debug_pass_max_attempts=2` но для теста, не для патчей.

## Архитектурный smell-check

- **Mode не спасает структурную проблему write_file**. Это пересмотр гипотезы: «правильный workflow покрывает» оказался слабым.
- **iterative_patch_loop без mode-specific retry policy** — все retry дёргают тот же tool. Нужно либо запретить write_file overwrite во второй попытке (force SR), либо переоценить tool-set для code-mode.
- **SR-format у 14b работает (23/24 на бенче)**, но native function calling переучил модель приоритизировать write_file. Это **архитектурное последствие** v0.3.x перехода на native fn calls, которое мы тогда видели как улучшение (глава 4 девлога) — но трейд-офф был незаметен.

## Verdict

**1/5**. Mode-фикс работает на уровне инфраструктуры (ask чистый, code запускает code_with_retry), но **продуктово хуже** чем чистый ask: те же поломки + retry усугубляет + 44% больше токенов.

## Список дальнейших действий

(В backlog, не делаю сейчас.)
- **plan.md**: hard guard на `write_file` для существующих .py (только range или новый файл).
- **plan.md**: few-shot SR-edit в `prompts/system.md`.
- **plan.md**: anti-loop для write_file ретраев (аналог debug_pass_max_attempts).
- **plan.md**: пересмотр default-выбора формата патча в code mode — приоритет SR.
- **Это самое важное наблюдение из всего пилота**: «mode правильный, инструмент `write_file` неправильный для большинства правок».

# Evaluation: c_fix_bug-mini_cli_with_bug-450cf87-20260513-153012

## One-liner

Swap-инфраструктура работает на уровне инфры (qwen→gemma load/unload через REST), но c_fix_bug builder-level не активирует forks — gemma не понадобилась. Builder опять сломал core.py при write_file (потеря @dataclass, ручной __init__ вместо генерируемого).

## Trajectory

- **Setup**: `probe start c_fix_bug mini_cli_with_bug --upstream-model google/gemma-4-26b-a4b` после merge PR #79. Runner проверил downloaded list, gemma в нём — OK. Baseline qwen-14b загружен. swap_to при flush должен сработать.
- **Turn 1**: scalpel сделал run_tests → read_file(test_core.py) → write_file core.py → run_tests → write_file. Диагностика правильная (написал в reply что нужно добавить `self._write(items)` в mark_done). Но при write_file опять полный overwrite — структура файла сломана: пропал `@dataclass`, появился ручной `__init__(self, id, text, done)`.
- **Turn 2**: «применяй и закоммить» — scalpel в reply снова описал fix, **повторил последние два сообщения слово в слово** («Извините за путаницу. Давайте рассмотрим текущую ситуацию…») — снова семантическая петля как в #1.

## Главное наблюдение

**Swap не сработал не потому что инфра не работает, а потому что builder-level fix-bug не делегирует**. Никаких forks за 2 turn'а — следовательно `upstream_queue` пустая, `flush_upstream` не вызывается, swap-контекст не активируется. Gemma в памяти не оказалась, но **корректно** — runner про это знает (baseline reset на старте).

Чтобы измерить swap нужны сценарии с реальными forks (`b_spec_plan`, `d_new_feature`) — это в PROTOCOL.md записано.

## Повторение паттерна #1

Тот же 14b в том же ask mode на том же сценарии → тот же исход:
- правильная диагностика
- битый write_file overwrite
- семантическая петля во втором turn'е

Это **детерминирующее** поведение, не seed-зависимое. Подтверждает гипотезу из #1 evaluation: проблема в **сочетании** «write_file overwrite + ask mode + 14b», не в одной из компонент.

## Verdict

**1/5 как «swap-тест»** — swap-orchestration ни разу не активировалась. **2/5 как «детерминизм-чек»** — поведение builder воспроизвелось точь-в-точь, это валидное знание о стабильности.

Реальный swap-тест требует:
1. `--mode plan` + `probe go` в runner (task #32)
2. сценария с явными forks (например, `b_spec_plan`)
3. потом — повтор со swap'ом

## Список дальнейших действий

Никаких новых пунктов — всё уже в `scripts/probes_v2/PROTOCOL.md` секция «Текущие ограничения runner'а». Этот прогон подтверждает их и закрывает pilot-серию.

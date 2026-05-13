# User plan: c_fix_bug-mini_cli_with_bug-00916ae-20260513-145908

## Что я хочу добиться

Повтор probe #1 с upstream-свапом на `gemma-4-26b-a4b-it-assistant`.
Тот же баг (`mark_done` без `_write`), тот же juniors-стиль реплик.
Цель — увидеть:
- помогает ли свап избежать «поломки структуры» write_file
- передаёт ли scalpel этот fork upstream'у вообще, или fix-задача
  идёт целиком на builder'е (а upstream только для критичных forks)
- сравнить трудозатраты с #1

## Reference replies

Те же что в #1, чтобы прогон был сопоставим.

- turn 1: «pytest падает, разберись пожалуйста. недавно правил core.py, может там»
- turn 2 (если предложит fix): «ну ок, нашёл. почини и закоммить»
- turn 3+: реактивно по обстоятельствам

## Что НЕ говорю

То же что в #1: `mark_done` напрямую не упоминаю, не подсказываю
fix.

Если scalpel начнёт ломать структуру (как в #1) — фиксирую и
закрываю на 3-м turn'е. Если справится без contamination —
task_solved.

## Критерии остановки

- task_solved: pytest exit 0 + git commit landed
- user_gave_up: повторение паттерна #1 (битый write_file)
- error: LM Studio упала / демон умер

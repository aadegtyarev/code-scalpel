# User plan: c_fix_bug-mini_cli_with_bug-450cf87-20260513-153012

## Что я хочу добиться

Повторный прогон #3 после merge swap orchestration (PR #79).
В предыдущей попытке (#3 на ad51ab8) gemma не была загружена и
runner это не проверял → error. Сейчас runner на старте reset'ит
baseline (qwen-14b), swap_to при flush_upstream сам выгрузит
qwen и загрузит gemma.

Тот же сценарий что и #1: pytest падает на mark_done, scalpel
должен починить. Главный вопрос: **дойдёт ли builder до fork'а
который пойдёт в upstream**? На c_fix_bug fork'ов обычно не
бывает — это builder-level задача. Если builder отработает и
ни одного fork'а не сгенерирует — это сильный сигнал что
c_fix_bug сценарий для тестирования swap'а не подходит.

## Reference replies

Те же что в #1 — для сопоставимости.

- turn 1: «pytest падает, разберись пожалуйста. недавно правил core.py, может там»
- turn 2 (если diagnosed): «ну ок, нашёл. почини и закоммить»

## Что НЕ говорю

То же что в #1.

## Критерии остановки

- task_solved: pytest passes + commit + (бонус) хотя бы один fork улетел в upstream
- user_gave_up: повторение паттерна #1 (битый write_file)
- error: swap orchestration упала

## Ожидания

Вероятно `c_fix_bug` не даст forks → swap orchestration **никогда
не сработает**. Это **тоже валидный результат** — он показывает
архитектурное несоответствие: «swap имеет смысл для planning
сценариев, не для fix-bug».

# Evaluation: c_fix_bug-mini_cli_with_bug-00916ae-20260513-145908

## One-liner

Свап **физически невозможен** в текущей конфигурации — gemma не была загружена в LM Studio, runner не проверил это перед стартом; прогон aborted на 1-м turn, 30k токенов на бесплодный builder-loop.

## Trajectory

- **Setup**: `probe start c_fix_bug mini_cli_with_bug --upstream-model gemma-4-26b-a4b-it-assistant`. Runner создал `UpstreamProfile(model=gemma-...)` в daemon, передал в Runtime. **Runner проверил только `model_name_actual` базовой модели** (qwen-14b есть) и НЕ проверил доступна ли gemma. Это **моя ошибка реализации** — я добавил `_detect_lmstudio_model` для baseline, забыл сделать аналог для upstream.
- **Turn 1**: scalpel начал работу как в probe #1. 5 tool calls (run_tests → read_file mark_done → project_map → read_file core.py → read_file test). Снова правильно увидел `test_mark_done_flips_flag` падающим, дошёл до анализа `mark_done`. Tool-loop работает, **никакой fork не сработал** — задача fix-bug рутинная для builder'а, в неё нет архитектурных развилок которые бы делегировались upstream'у. Так что `UpstreamForker` за turn 1 ни разу не вызвался — gemma не понадобилась бы даже если была.
- **Stop**: пользователь заметил что gemma в LM Studio не загружена ([Loaded Models показал только `qwen/qwen2.5-coder-14b`](https://lmstudio.ai)). Финализировал как error — продолжать прогон бессмысленно: если бы scalpel дошёл до fork, `UpstreamForker.resolve` упал бы с 404/timeout от LM Studio.

## Хорошо (наблюдения, не правки)

- **fork-инфраструктура не вмешалась в builder loop**. UpstreamProfile создан, queue инициализирован, но scalpel не дёрнул `fork()` ни разу за 5 tool calls — потому что задача «fix bug» не предполагает архитектурных решений. Хорошо: upstream-конфиг не ломает поведение когда не нужен.
- **Turn 1 шёл по тому же паттерну что probe #1** — без `gemma` стороны эффекта. То есть baseline-поведение **детерминированно** на этой задаче (project_map → read → run_tests), что приятно для воспроизводимости.

## Плохо (наблюдения, не правки)

- **Главное: runner не валидирует upstream-модель**. Я добавил `_detect_lmstudio_model` для базовой модели, но забыл аналог для upstream. Параметр `--upstream-model gemma-...` прошёл silently, и если бы scalpel дошёл до fork — прогон умер бы on-demand с криптовым 404.
- **Концептуальная проблема: «swap» как идея существует только наполовину**. Что мы реально умеем (v0.12):
  - `UpstreamProfile` создаётся
  - `UpstreamPendingQueue` собирает forks
  - `Runtime.flush_upstream` дёргает `UpstreamForker.resolve` который шлёт в указанный base_url + model
  Чего мы **не умеем** (но нужно для свапа):
  - проверить что upstream-модель доступна на этом base_url до запроса
  - дать команду LM Studio «загрузи модель X» (в REST API LM Studio это вроде есть, но мы её не дёргаем)
  - дождаться unload qwen и load gemma → выполнить запрос → опционально вернуть qwen
- **c_fix_bug не даёт forks**: для этого сценария upstream-свап в принципе не активируется. Это сильный сигнал: чтобы тестировать swap, нужны сценарии с явными forks выбора (planning со стеком, архитектурные развилки). `b_spec_plan` потенциально лучше для probe-swap.

## Гипотезы о причинах

- **runner-bug**: `_detect_lmstudio_model` написан только под baseline, я не сделал аналог для upstream. Исправляется в 5 минут.
- **LM Studio не сама свапает по запросу другой model id**: если модель не в `state: loaded`, запрос вернёт ошибку. Auto-evict / on-demand load — отдельная фича LM Studio, и для её использования нужно дёргать REST API (`POST /v1/models/<id>/load` примерно).
- **Сценарий c_fix_bug не имеет forks**: задача чисто builder-level (read → patch → test). Чтобы у нас вообще что-то ушло в upstream, нужен сценарий с реальной развилкой («какой стек?», «какую структуру данных?»).

## Как теоретически можно было бы лечить

1. **Сразу: добавить проверку upstream-модели в `cli.start`**. По аналогии с baseline: проверить что `--upstream-model` есть в `/v1/models` list или хотя бы fail-fast если LM Studio говорит «нет такой».
2. **Свап через LM Studio REST API**. Перед прогоном со swap — runner вызывает `POST /v1/models/<gemma>/load` (или эквивалент), ждёт пока модель reach `state: loaded`, и только тогда передаёт control daemon'у. После прогона можно `unload`. Это **продуктовая работа** для основного scalpel'а — `UpstreamForker.resolve` должен сам уметь swap'ать модели когда у нас один base_url (см. главу 27 девлога — мы это обсуждали).
3. **Тестировать swap на planning-сценарии (`b_spec_plan`)**. Там есть реальные forks типа «какой парсер ярлыков», «JSON vs SQLite». На fix-bug свапа не будет.

## Архитектурный smell-check

- **Архитектура v0.12 для upstream обещает больше чем умеет**. `UpstreamProfile` + `UpstreamPendingQueue` + `flush_upstream` — это framework для batch-резолюции, **но автоматического переключения модели на стороне LM Studio нет**. Когда мы передаём `--upstream-model X`, мы предполагаем что X уже в `state: loaded`. На локальной машине с одним GPU это **физически невозможно одновременно** с qwen-14b (VRAM не вмещает).
- **Это известная архитектурная дырка** — в плане §31 v0.12 мы её специально отметили («когда появится возможность сделать swap»). Сейчас probe это **наглядно показал**.
- **fork-инфраструктура** работает корректно: scalpel **не зовёт fork** на builder-level задачах, как и должно быть. Делегирование upstream сработает только когда реально появится архитектурная развилка.

## Трудозатраты (субъективно)

1 user-turn, 30k токенов, 5 tool calls — всё на baseline-работе которая не требовала свапа. Прогон финализирован как `error` потому что **проверка инфраструктуры провалена**, не потому что scalpel плохо отработал. По turn-by-turn — он шёл хорошо.

Wall time 113 сек.

## Verdict

**1/5 как «свап-тест»**, потому что свапа не было — gemma даже не была в памяти. **3/5 как «тест baseline под upstream-конфигом»** — поведение builder идентично probe #1 первому turn'у, что подтверждает детерминизм.

Чистого замера эффекта swap'а **этот прогон не дал**. Нужен setup с реально загруженной gemma в LM Studio (вручную через UI или через REST swap до старта probe).

## Список дальнейших действий

- **Хотфикс runner'а**: добавить `_check_upstream_model_loaded()` в `cli.start`. Fail-fast если упомянутая в `--upstream-model` модель не в `/v1/models` (или не loaded если LM Studio даёт state).
- **plan.md backlog**: **LM Studio swap orchestration**. Перед `flush_upstream` — REST-команда «загрузи модель X», ожидание `state: loaded`, выполнение, опциональный возврат. Это для probe и для общего использования с локальной single-GPU машиной. Раньше мы это обсуждали (главa 27 девлога) и записывали как TODO — пора предметно поднять.
- **Probe re-run #3**: после хотфикса + ручной загрузки gemma — повторить тот же сценарий, чтобы получить чистый замер. Лучше попробовать вариант с реальной развилкой — например `b_spec_plan` (когда сделаю).
- **Сейчас не чиним** — фиксы остаются как backlog. Возвращаюсь к серии прогонов: пишу хотфикс проверки upstream-модели, потом следующий план зависит от того, готов ли пользователь руками свапнуть gemma в LM Studio.

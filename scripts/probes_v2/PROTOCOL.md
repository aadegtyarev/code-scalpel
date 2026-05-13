# Probe-suite v2 — Protocol

Протокол живого прогона. Я (Claude) играю роль юзера согласно
[user_tone_of_voice](../../memory/user_tone_of_voice.md), общаюсь
со scalpel-агентом (qwen2.5-coder-14b внутри), фиксирую
артефакты в `docs/article/probe-runs/<run-id>/`. Цели и контекст
зачем — в [девлоге глава 33](../../docs/article/v1_devlog.md).

## Конфигурация (зафиксировано)

| Параметр | Значение |
|---|---|
| Модель агента | `qwen2.5-coder-14b` в LM Studio на `localhost:1234` |
| Юзер | я-Claude по `user_tone_of_voice.md`, не автомат |
| Оценка | пост-фактум, я пишу `evaluation.md` |
| Timeout одного ответа scalpel'а | 180 сек |
| Max turns в одном прогоне | 20, дальше force-finalize |
| Критерий «сдаюсь» | свободное решение, причина в `evaluation.md` |
| Артефакты | `docs/article/probe-runs/<run-id>/`, в git |
| Fixture | полный `tar.gz` в каждом прогоне |
| Реестр | `docs/article/probe-runs/INDEX.md`, обновляется после каждого finalize |

## Иерархия метрик

**Первичная**: **задача решена?** — binary, по `verdict.json.criteria`
(pytest exit 0 / TASKS.md валиден / новый тест проходит — зависит
от сценария). Если решена ровно нигде — сильный сигнал, числа
вторичны.

**Вторичная** (когда первичная = true): трудозатраты —
`user_turns`, `agent_llm_requests`, `prompt+completion_tokens`,
`prompt_tokens_peak`, `retries`, `tool_calls_total/by_name`,
`wall_time_sec` из `metrics.json`.

Если задача не решена — те же числа лежат рядом, но читаются
как диагностика «куда ушло время», не как мера эффективности.

## CLI команды runner'а

Всё через `scripts/probes_v2/cli.py`. Реализация — отдельный PR.

```bash
# Старт нового прогона
probe start <scenario> <project>
  # → создаёт run-id, папку, разворачивает fixture в tmp-workdir,
  # → запускает Runtime-демон в фоне, печатает run-id

# Один turn диалога
probe step <run-id> "реплика юзера"
  # → демон обрабатывает реплику через runtime.stream(...)
  # → recorder пишет chat.jsonl, tools.jsonl, timing.json
  # → возвращает ответ scalpel'а в stdout

# Свободная заметка по ходу
probe note <run-id> "заметка"
  # → дописывает в notes.md (с timestamp'ом)

# Завершение
probe finalize <run-id> --reason=<task_solved|user_gave_up|error>
  # → останавливает демон, снапшотит final_tree/,
  # → собирает metrics.json, прогоняет мехчекеры → verdict.json,
  # → копирует TASKS.md scalpel'а → agent_plan.md (если был),
  # → дописывает строку в INDEX.md

# Просмотр статуса
probe status <run-id>     # текущее состояние демона / счётчики
probe list                # все прогоны (читает INDEX.md)
```

## Шаги одного прогона

### 0. Перед серией прогонов (одноразово)

- LM Studio запущена с `qwen2.5-coder-14b`
- репо в чистом состоянии (для воспроизводимости `git_sha` в `meta.json`)
- никаких других прогонов в фоне (`probe list --active`)

### 1. Старт

`probe start <scenario> <project>` → получаю `<run-id>`.

run-id формат: `<scenario>-<project>-<sha>-<YYYYMMDD-HHMMSS>`.
Пример: `c_fix_bug-mini_cli-a1b2c3d-20260513-1730`.

После `start` в папке `<run-id>/` лежат заглушки всех файлов
+ заполненные `meta.json`, `scenario.md`, `fixture_initial.tar.gz`.

### 2. Я пишу `user_plan.md`

До первой реплики. По шаблону:

```markdown
# User plan: <run-id>

## Что я хочу добиться
...

## Как буду себя вести (стиль)
По [user_tone_of_voice](../../../memory/user_tone_of_voice.md).

## Что НЕ говорю
Например: не подсказываю где именно баг — пусть scalpel сам найдёт.

## Reference replies (если планировал заранее)
- turn 1: «...»
- turn 2: «...»
```

### 3. Цикл диалога

Моя сторона: формулирую реплику в характерном тоне → `probe step <run-id> "..."` → читаю ответ scalpel'а → формулирую следующую.

Recorder в реальном времени пишет:
- `chat.jsonl` — мой turn + ответ модели (с usage / request_id / tokens / timestamp)
- `tools.jsonl` — каждый tool call: name, args, output, ok, diff
- `timing.json` — таймлайн событий (start_turn, llm_call, tool_call, end_turn)

По ходу могу `probe note <run-id> "scalpel прочитал не тот файл, дам подсказку"` — пишется в `notes.md`.

### 4. Завершение

Один из трёх исходов:
- задача решена по моему ощущению (`task_solved`)
- я сдался (`user_gave_up`) — мотивация в evaluation
- ошибка инфраструктуры (`error`) — LM Studio упала, демон умер, etc

`probe finalize <run-id> --reason=<...>`:
- демон останавливается
- финальный snapshot tmp-workdir → `<run-id>/final_tree/`
- session stats → `metrics.json`
- мехчекеры из `scenario.md` → `verdict.json`
- `TASKS.md` scalpel'а → `agent_plan.md` (если генерировался)
- дописывает строку в `INDEX.md`

### 5. Я пишу `evaluation.md`

**Важно**: я не чиню код в моменте прогона. Записываю наблюдение
+ гипотезу о причине + теоретический способ лечения + что это
говорит об архитектуре. Конкретные правки — потом, отдельным
пайплайном после серии.

Шаблон:

```markdown
# Evaluation: <run-id>

## One-liner
Одна фраза для INDEX.md: «Нашёл баг с 3 turn'ов, потратил
8k токенов, retries 1».

## Trajectory
3-5 предложений: как прошёл диалог.

## Хорошо
- ...

## Плохо (наблюдения, не правки)
- Что именно пошло не так. Где. Цитата из chat.jsonl/tools.jsonl.

## Гипотезы о причинах
Для каждого «плохо» — почему scalpel так себя повёл.
- Недостаток в данных? (например, MAP не имел нужного docstring'а)
- Недостаток в промпте? (модель не поняла что от неё хотят)
- Недостаток в архитектуре? (нет нужного tool'а / нет нужного guard'а)
- Свойство модели? (14b в принципе тут не вытянет)
Гипотезы — не диагноз; ставим вопрос, не приговор.

## Как теоретически можно было бы лечить
По каждой гипотезе — что попробовать. Без обязательств реализации.
- Обогатить MAP таким-то полем.
- Добавить post-hoc guard на N.
- Дать новый tool X.
- Сменить модель / fallback.
- Принять что эту задачу 14b не вытягивает, документировать как
  «нужен upstream».

## Архитектурный smell-check
Что эта ситуация говорит о принятых решениях? Верны ли они в
ретроспективе?
- Например: «решение про write_file как единый инструмент с
  тремя режимами здесь работает» / «не работает потому что Y».
- Подтверждает или опровергает выбор, сделанный в главе N
  девлога.

## Трудозатраты (субъективно)
Turn'ов мне понадобилось / ожидание vs реальность / был ли flow
комфортным.

## Verdict
1-5 с обоснованием. Не путать с verdict.json (мехчекеры).

## Список дальнейших действий
Конкретные пункты — куда: plan.md / backlog / следующий probe /
обсудить с пользователем. Без обязательств немедленно делать.
```

`One-liner` копируется в INDEX.md как поле «summary». Остальные
секции читаются когда садимся за плановую итерацию исправлений
или за статью.

### 6. Архивация

```bash
git add docs/article/probe-runs/<run-id>/
git commit -m "probe: <run-id> — <one-liner>"
gh pr create ... && gh pr merge ...
```

Каждый прогон или серия прогонов = свой PR в main.

## Структура артефактов

```
docs/article/probe-runs/<run-id>/
  meta.json                  # run_id, scenario, project, version_tag, git_sha,
                             #   model_name, base_url, context_tokens,
                             #   started_at, ended_at, ended_reason, user_role,
                             #   command, env
  scenario.md                # описание + критерии успеха + моя роль
                             #   (копия — историчные прогоны помнят как было)
  fixture_initial.tar.gz     # стартовый snapshot (полный, с .git)
  chat.jsonl                 # все turns: {ts, role, content, tokens?, request_id?}
  tools.jsonl                # tool calls: {ts, name, args, output, ok, diff?}
  agent_plan.md              # TASKS.md scalpel'а или заглушка
  user_plan.md               # мой план перед стартом
  final_tree/                # снапшот после прогона (раскрытый)
  metrics.json               # user_turns, agent_llm_requests,
                             #   prompt/completion_tokens_*, prompt_tokens_peak,
                             #   tool_calls_total/by_name, retries,
                             #   commits_landed, wall_time_sec
  timing.json                # таймлайн событий
  verdict.json               # мехчекеры: pass_score, pass_max, criteria
  evaluation.md              # мой пост-мортем (см. шаблон выше)
  figures/                   # свои графики прогона (если есть)
  notes.md                   # свободные заметки по ходу
```

Если артефакт неприменим — заглушка с пометкой почему.

## Сценарии (pilot)

| ID | Тип | Старт | Pass-критерии (mechchecker) |
|---|---|---|---|
| `a_diag_plan` | Диалог-планирование | пустая дир | `tasks_md_present`, `tasks_count_ge_3`, `tasks_have_required_fields`, `paths_valid` |
| `c_fix_bug` | Фикс бага | `mini_cli_with_bug` (тест падает) | `tests_pass`, `commits_landed_ge_1`, `no_uncommitted_changes` |

Сценарии `b_spec_plan` (ТЗ-планирование) и `d_new_feature` (новая
фича) — после pilot. `verdict.json.criteria` — все четыре сценария
заполняют поля по своему набору, неприменимые = `null`.

## Edge-кейсы

| Что | Как |
|---|---|
| LM Studio упала | `probe finalize --reason=error`, обстоятельства в `notes.md` |
| Тупик и я сам сдаюсь | `probe finalize --reason=user_gave_up`, причина в evaluation |
| scalpel завис >180 сек | `probe step` возвращает timeout, я решаю — переформулировать или сдаться |
| Я случайно подсказал решение | `probe note "contaminated turn N: подсказал X"`, в evaluation помечаю; verdict валиден если scalpel реально решил по другому turn'у |

## Реестр (INDEX.md)

`docs/article/probe-runs/INDEX.md` — общий каталог. Обновляется
автоматически на `probe finalize`. Колонки:

| run-id | date | scenario | project | version | verdict | turns | tokens | one-liner |
|---|---|---|---|---|---|---|---|---|

Поиск через `grep` по `INDEX.md` — самый практичный путь:
- по теме: `grep "fix_bug" INDEX.md`
- по версии: `grep "v0.10" INDEX.md`
- по результату: `grep "user_gave_up" INDEX.md`
- по содержимому one-liner: `grep "retry" INDEX.md`

## Семантика mode'ов — реплики юзера

Контекст `_history` сохраняется между mode'ами автоматически
(`StepAgent._history` живёт в инстансе, не зависит от mode).
Переключение mode меняет **только** system-prompt addendum +
temperature + поведение (ask/plan не патчат, code патчит).

**Правило юзера (я-Claude в probe-сессиях)**: реплики должны
соответствовать жанру mode'а. Нельзя смешивать «разберись и
почини» в одной реплике — это две разные задачи разных режимов.

| Mode | Что юзер ПРОСИТ | Что юзер НЕ просит |
|---|---|---|
| `ask` | объясни / прочитай / какие гипотезы / помоги понять / какой подход | не «поправь», не «закоммить» |
| `plan` | составь план / разложи на задачи / TASKS.md по этому | не реализуй, не патчь |
| `code` | поправь / реализуй / добавь / закоммить | не «объясни почему», не «составь план» |
| `review` | проверь diff / оцени план / найди проблемы | не «поправь», не «измени» |

Workflow для типового probe-сценария:
1. `step --mode ask` — обсудить ситуацию, попросить диагноз
2. `step --mode plan` — попросить план если задача нетривиальная
3. `step --mode code` ИЛИ `go` — реализация
4. (опц.) `step --mode review` — финальный sanity-check

Каждый сценарий в `scenarios/*.md` описывает **какие модами он
пользуется и в каком порядке**, плюс reference replies для
каждого mode'а.

## Текущие ограничения runner'а

Здесь — ровно про **probe-инструментарий**, не про продукт. Когда
закрываем пункт — удаляем его отсюда. В `docs/plan.md` это
**не** идёт.

- [ ] **Mode-переключение в probe-сессии**.
      Сейчас `daemon.handle_step()` хардкодит `runtime.agent.ask(...)`
      → все turn'ы идут в `ask` mode. Реальный workflow scalpel'а:
      «обсудили (ask/plan) → `/plan` → TASKS.md → `/go` → run_plan
      в code mode с retry». Probe этого **не моделирует**, поэтому
      пилоты #1–#3 мерят ask-режим, а не продукт целиком.
      Нужно:
        - `probe step --mode {ask|plan|code|review}` — выбор режима
          для конкретного turn'а;
        - `probe go <run-id>` — отдельная команда, дёргает
          `runtime.agent.run_plan()` (то есть автоматический
          patch-loop в code mode на сгенерированном TASKS.md).
      Автопереключение режимов в TUI (Ctrl+T) появилось недавно —
      probe пока не использует, переключаем вручную через `--mode`.

- [ ] **Mechcheckers в коде finalize**.
      Сейчас `verdict.json` после `probe finalize` несёт только
      `ended_reason` + пустой `criteria{}`. Сценарные критерии
      (`tests_pass`, `tasks_md_present` etc) описаны в `scenarios/*.md`
      словами, но в коде не проверяются. Нужно: парсер scenario.md
      или маппинг `scenario → checker[]` в `scripts/probes_v2/mechcheckers.py`,
      и `finalize` запускает соответствующие checker'ы → пишет
      результаты в `verdict.json.criteria`.

- [ ] **Channel-unification через `Session.prepare_turn` повторяется в демоне**.
      `daemon.handle_step` сам вызывает `self.runtime.session.prepare_turn(text)`
      перед `agent.ask(task, on_tool_executed=...)` — потому что
      `runtime.ask()` делает prepare_turn, но **не принимает**
      `on_tool_executed`. Нарушение «один entry point», обсуждённое
      в главе 17 девлога. Лечение — на стороне продукта (расширить
      `Runtime.ask/stream` параметром), но это **просьба от probe**,
      не общая нужда. Записано здесь как ограничение probe, не в
      plan.md как фича.

- [ ] **Swap-сценарий: c_fix_bug не активирует upstream**.
      Probe pilot #3b показал: swap-инфраструктура работает (PR #79),
      но на `c_fix_bug` форки не возникают — builder-уровневая
      задача (read + patch + test) не требует архитектурных решений.
      Для **измерения swap'а** нужны сценарии с реальными forks:
      `b_spec_plan` (выбор стека) или `d_new_feature` (как лучше
      добавить функционал — несколько подходов). Добавить их в
      `scenarios/` отдельным PR'ом после `--mode` пилота.

## Historical: level-based прогрессия задач

**Принцип:** одна задача-нарратив на все версии, но **scope
действия растёт** с capabilities. На v0.3 — план словами в reply.
На v0.7 — план + чтение проекта. На v0.10 — план + fork. На
v0.12 — план + fork + upstream override. Каждый тэг получает
**верхний достижимый level** — то что версия физически
может сделать.

**Базовая задача-нарратив** (одна на всю серию):
**«спроектируй python-CLI для заметок: команды add / list /
search / delete. JSON-storage. pytest. Расскажи как построить.»**
Дальше — с расширением action-scope:

| Level | Что просим **сверх** предыдущего | Capability | Версии |
|---|---|---|---|
| **L1** | только план в reply, словами | reply связный | v0.3, v0.4 |
| **L2** | + код через SR-блоки в reply (main.py / core.py) | code_with_retry / SR-edits | v0.5 |
| **L3** | + создать файлы прямо в проекте | write_file | v0.6, v0.7 |
| **L4** | + TASKS.md в нашем DSL | plan mode + annotate | v0.8, v0.9 |
| **L5** | + автоматическое /go выполнение | run_plan + machine guards | v0.8, v0.9 (вместе с L4) |
| **L6** | + fork «стек: SQLite vs flat JSON?» с обоснованием | Fork API | v0.10, v0.11 |
| **L7** | + сложный fork «multi-user vs single-user storage?» в upstream gemma | upstream + swap | v0.12+ / main |

**Правила:**
- Задача переформулируется когда добавляется scope, но **тезис не
  меняется**: всё та же заметочница.
- На каждой версии — **верхний** level. Не «v0.3 не справился с
  L3» (это очевидно); а «v0.3 на L1: справился / не справился /
  частично».
- 1-2 версии **до** capability landing'а гонять предыдущий level
  чтобы зафиксировать «здесь ещё нет».
- Реплики юзера соответствуют **mode'у** turn'а (см. секцию
  «Семантика mode'ов»).

**Параллельная ось — legacy probe pack:**

На каждой версии гоняем готовые `scripts/probe_*.py` — точечные
метрики без шума живого диалога:
- `probe.py` — basic /ask, отвечает ли модель
- `probe_code.py` — 24-test patch pass rate (главное!)
- `probe_forks.py` — fork resolution 12/12 (v0.10+)
- `probe_fork_reviewer.py` — reviewer 5/6 × 3 темп (v0.11+)
- `probe_e2e_forks.py` — e2e /go стек (v0.11+)

Артефакты: `docs/article/probe-runs/legacy/<tag>/{probe}.txt`.
Это даёт **числовой timeline** для графиков статьи — pass rate
× версия. Live-probe даёт **нарратив** к этим числам.

## История по тэгам (один runner, идентичные условия)

**Главный принцип: probe-runner один и тот же на всех тэгах.** Не
адаптируем код под версии — иначе невозможно сравнивать. Если
на старом тэге чего-то не хватает (нет `Runtime`, нет
`ToolResult.diff`, нет fork_resolver) — runner это ловит через
`try/except ImportError/TypeError` и записывает в
`meta.json.adaptations` как **наблюдение**, не молча подменяет.

Сценарий идентичен между версиями: те же fixture, те же реплики,
тот же mode (в `step --mode`). Меняется только версия scalpel'а
под тестом. Это даёт **сопоставимые** результаты прогонов:
«на main это решилось за 5 turn'ов, на v0.6 не решилось вообще».

Что мы заранее знаем про несовместимости (предварительная карта,
уточним когда упрёмся):

| Версия | Что отсутствует |
|---|---|
| ≤v0.3.0 | `Runtime`-orchestrator (был только StepAgent), `mode=` параметр у ask мог не быть |
| ≤v0.5.0 | `ToolResult.diff` ещё не существует — `diff=None` для всех write_file |
| ≤v0.7.0 | `on_tool_executed` в run_plan появился позднее (probe станет слеп по tools) |
| ≤v0.10.0 | Fork API + `fork_resolver` параметр |
| ≤v0.12.0 | `UpstreamPendingQueue`, `flush_upstream`, swap orchestration |

Если probe-runner упадёт на import — переходит в degraded mode:
пишет что упало, помечает прогон как `aborted_by_runner_incompat`,
двигается к следующему тэгу. Это **тоже данные** для статьи.

## Связь со старыми probe'ами

Не заменяет. Старые `probe_forks` / `probe_fork_reviewer` /
`probe_e2e_forks` / `probe_code` / `probe_recipes` — точечные
быстрые регрессы для отдельных каналов (fork API,
reviewer, etc). v2 — широкий замер живых задач.

Перед каждым PR с поведенческими изменениями: гоняем старые
(быстро), плюс минимум один pilot-кейс v2 (медленно, но реалистично).

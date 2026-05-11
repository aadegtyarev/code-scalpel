# code-scalpel

TUI coding agent для работы с кодом через **слабые локальные LLM**.
Принцип: маленький контекст, маленький patch, быстрый тест,
контролируемая автономность.

> Статус: v0.3 в работе. v0.1 (proof-of-concept) и v0.2 (tool-loop +
> grounding + transparency) закрыты. См. `docs/plan.md` §31.

## Зачем

Большие облачные модели (Claude, GPT) умеют редактировать код по тексту.
Локальные 7-30B модели — нет, или плохо: галлюцинируют, теряют
контекст, генерят патчи которые не применяются.

`code-scalpel` — это **harness** который заставляет слабую модель
вести себя надёжно:

- **компактный project map** вместо дампа файлов — `class Session` +
  сигнатуры методов, без тел. ~1k токенов на проект из 30 файлов
  вместо 7k.
- **native function-calling** (read_file / grep / run_tests) — модель
  запрашивает что ей нужно, а не получает всё сразу.
- **строгие grounding rules** в промте — «если символа нет в map, его
  нет; перед показом кода обязательно read_file».
- **per-mode temperature** — ask=0.1, code=0.2, debug=0.5. Чтобы
  retrieval не выдумывал, а edit-режим не был дубовым.
- **SEARCH/REPLACE patch format** — модель выдаёт diff, мы применяем
  атомарно. Никаких полу-применённых файлов.

Тестовая модель: `qwen2.5-coder-14b-instruct` в LM Studio. На 28-тест
бенче: **29/30 passing** (одна non-deterministic flake).

Кросс-модельный бенч (7 моделей, см. `docs/bench-models.md`): coder-14b
лучший Pareto, gemma-4-26b-a4b лучшее качество (100%) но в 2.5× медленнее.

## Установка

```bash
# 1) Окружение
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2) LM Studio (отдельно): https://lmstudio.ai
#    Загрузить qwen2.5-coder-14b-instruct, запустить server на :1234.
```

Альтернативный backend — собранный из исходников `llama.cpp` с CUDA:

```bash
~/src/llama.cpp/build/bin/llama-server \
  --model path/to/qwen2.5-coder-14b-Q4_K_M.gguf \
  --port 1234 -ngl 99 --host 127.0.0.1
```

## Запуск

```bash
cd ваш-проект
code-scalpel
```

TUI откроется в текущей папке. Слева футер:
`[ctrl+t] cycle mode · [ctrl+q] quit · ● idle · qwen2.5-coder-14b`.

После каждого ответа модели в чате появляется dim-строчка-сводка:

```
⤷ 🔧 2 tools · ↓ 234 tokens · 5 tok/s · 1.4s · ctx 1k/16k (6%)
```

Жёлтое `⚠ no tools used` означает что модель не звала ни одной
тулзы — высокий шанс что ответ confabulated, проверь через `/map`.

## Режимы

| Режим | Temp | Назначение |
|---|---|---|
| `ask` | 0.1 | Q&A, retrieval, обсуждение. Не меняет код. |
| `plan` | 0.4 | Планирование, TASKS.md *(v0.3+)*. |
| `code` | 0.2 | Один шаг — модель пишет SEARCH/REPLACE patch. |
| `review` | 0.1 | Анализ, code review *(v0.3+)*. |
| `debug` | 0.5 | Sub-режим для regen после неудачи. |

Переключение: `Ctrl+T` или `/mode ask|plan|code|review`.

## Слаш-команды

| | |
|---|---|
| `/new` | Очистить сессию (chat + state + history). |
| `/compact` | Суммаризировать историю в одно сообщение. Освобождает контекст. |
| `/map` | Показать project map (что модель видит каждый turn). Свёрнуто, Ctrl+O для full view. |
| `/help` | Список команд. |
| `/mode <name>` | Переключить режим. |

## Хоткеи

| | |
|---|---|
| `Ctrl+T` | Цикл по режимам |
| `Ctrl+O` | Открыть последний tool-result в попапе с подсветкой |
| `Ctrl+Q` | Выход |
| `Esc` | Прервать стриминг ответа |

## Тулзы

Модель вызывает их через native OpenAI function-calling. Все
результаты рендерятся inline как свёрнутые карточки.

| Тулза | Что |
|---|---|
| `read_file(path)` | Полное содержимое файла с номерами строк. |
| `grep(pattern, path?)` | До 30 совпадений по regex. |
| `run_tests(args?)` | `pytest`, exit code + truncated output. |

## Архитектура — коротко

```
TUI (Textual)
  └─ ScalpelApp
       ├─ OutputLog       ← inline chat
       ├─ ModeInput       ← цвет курсора по режиму
       └─ StatusFooter    ← минимальная: status + model
agent.StepAgent
  └─ stream_ask(task, mode)
       ├─ build user_msg = "Project map:\n<map>\n\nTask: <task>"
       ├─ chat() с tools=[read_file, grep, run_tests]
       │    └─ цикл: tool_call → execute → tool_result → ...
       └─ extract SEARCH/REPLACE → patch/edit_block.apply_edits
patch/edit_block
  └─ атомарное применение: tmp-файл → rename
tools/
  ├─ files.py, search.py, shell.py
  └─ agent_tools.py    ← JSON Schema для native function-calling
```

Полное описание: `docs/plan.md`.

## Конфиг

Дефолтные настройки заиграют без файла. Кастомизация:

```yaml
# ~/.config/code-scalpel/config.yaml  (системный)
# или .code-scalpel/config.yaml       (проект)
profiles:
  local:
    provider: lmstudio
    model: auto          # автодетект из /v1/models; явное имя override
    top_p: 0.9           # shared
    temperature:         # per-mode dict, или float = одинаково для всех
      ask: 0.1
      code: 0.2
      debug: 0.5
```

`model: auto` (или legacy `local-model`) — спросит LM Studio через
`/v1/models` и подставит первую загруженную. Явное имя
(`qwen2.5-coder-14b-instruct`) идёт в провайдер без изменений.

## Разработка

```bash
ruff check . && ruff format --check .
mypy code_scalpel/
pytest                          # 235 unit-тестов
pytest -m llm --run-llm         # 30 LLM-тестов под LM Studio
```

Тесты пишутся вместе с кодом, **не после**. Нет теста — нет коммита.

## Доки

- `docs/plan.md` — архитектура + роадмап (источник правды).
- `docs/prompts.md` — как писать промты и описания тулз для слабых LLM,
  с уроками из итерации 2026-05-11 (галлюцинация summary_line).
- `docs/bench-models.md` — кросс-модельный бенч, 7 моделей × 24 теста.
- `docs/article_draft.md` — техническая статья о проектировании.

## License

AGPL-3.0-or-later.

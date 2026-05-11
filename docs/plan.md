# code-scalpel

## 1. Идея

**code-scalpel** — TUI coding-agent для аккуратной работы с кодом через слабые локальные и облачные LLM.

Главная идея:

```text
маленькая задача
маленький контекст
маленький patch
быстрый тест
контролируемая автономность
```

Это не замена Claude Code и не «автономный программист».
Это инженерный помощник, который умеет:

- уточнять неоднозначные задачи;
- строить план;
- выбирать минимальный контекст;
- менять код через patch;
- показывать diff;
- запускать тесты;
- идти по плану до стоп-условия.

---

## 2. Назначение

Инструмент нужен для сценариев:

- добавить функцию в существующий проект;
- исправить баг;
- написать небольшую CLI/TUI/служебную утилиту;
- добавить тесты;
- провести небольшой рефакторинг;
- развивать проект пошагово на слабой локальной модели.

Типичный проект:

```text
10–100 файлов
100–500 строк на файл
контекст модели 16–32k
локальная LLM 7B–14B (тестируем на qwen2.5-coder-14b)
```

---

## 3. Стек

**Python 3.11+**

| Назначение | Библиотека | Почему |
|---|---|---|
| TUI | `textual` | современный, async-native |
| CLI | `typer` | строится поверх click |
| Конфиг | `pyyaml` + `pydantic` | yaml-файл + валидация схемы |
| Секреты | `python-dotenv` | `.env` → os.environ; ключи вне YAML |
| LLM | `openai` (AsyncOpenAI) | транспорт: SSE-стриминг, retry, connection pool |
| Diff parsing | `unidiff` | извлечь и распарсить unified diff из текста модели |
| .gitignore | `pathspec` | листать файлы с учётом .gitignore |
| Символы | `ast` (stdlib) | вытащить функции/классы из Python-файлов |
| Токены | `len(text) / 4` | грубая оценка бюджета; для локальных моделей достаточно |
| Git ops | `subprocess` | прямые вызовы git через ShellRunner |
| Ripgrep | `subprocess` | rg через ShellRunner |
| HTTP fetch | `httpx` | для `learn --url`; async, уже в зависимостях openai SDK |

LLM-провайдеры, поддерживаемые одним адаптером:

```text
LM Studio       http://localhost:1234/v1   (основной для разработки)
llama.cpp srv   http://localhost:8080/v1
OpenRouter      https://openrouter.ai/api/v1
vLLM, Ollama    (совместимы)
```

> **Future:** нативная интеграция с llama-cpp-python (прямая загрузка модели без HTTP-сервера).

---

## 4. Что делает

code-scalpel умеет:

- читать структуру проекта;
- искать код через ripgrep;
- читать только нужные файлы или фрагменты;
- задавать уточняющие вопросы;
- предлагать минимальное решение;
- разбивать задачу на подзадачи;
- генерировать unified diff;
- извлекать diff из ответа модели (strip prose);
- проверять patch перед применением;
- применять patch после подтверждения или в supervised mode;
- откатывать patch;
- запускать тесты;
- анализировать traceback;
- делать один или несколько debug attempts;
- суммаризировать контекст (шаги, файлы, сессию);
- сохранять и восстанавливать состояние задачи;
- обновлять индекс проекта;
- создавать новые recipes и skills через learn.

---

## 5. Что не делает в MVP

В MVP не нужно:

- полноценный web UI;
- multi-agent swarm;
- MCP-зоопарк;
- browser automation;
- embeddings и векторная база;
- автономная работа без стоп-условий;
- бесконтрольный рефакторинг;
- автоматическая установка зависимостей;
- изменение всего проекта одним запросом;
- хранение полной истории чата;
- нативный llamacpp без HTTP.

---

## 6. Режимы работы

Режимы — как в Claude Code build/plan, но в нашей терминологии.
Переключаются горячей клавишей прямо в TUI или через CLI.

```text
 ask   plan   code   run   review   learn
```

### ask

Разговорный режим: обсуждение, вопросы, планирование доработок — ничего не меняется в коде.
Может использовать INDEX metadata, ARCH.md, DECISIONS.md и ripgrep search.
Не читает полные исходные файлы. Никогда не модифицирует код.
Подходит для: "как лучше сделать X?", "где используется функция Y?", "разберём архитектуру".

CLI: `code-scalpel ask "..."` или просто ввести вопрос в TUI  
TUI hotkey: `[Tab]` → ask

### plan

Создать план, обсудить, уточнить — без выполнения.
Модель строит TASKS.md, задаёт вопросы. Переключиться в code/run чтобы выполнить.

CLI: `code-scalpel plan "..."`  
TUI hotkey: `[Tab]` → plan

### code *(manual; ранее `step`)*

Один шаг с подтверждением пользователя.

```text
agent proposes → user confirms → agent applies → agent tests
```

CLI: `code-scalpel code`  
TUI hotkey: `[Tab]` → code

### run *(supervised autonomous)*

Агент идёт по плану, останавливается при риске. Стоп-условия — раздел 28.

CLI: `code-scalpel run`  
TUI hotkey: `[Tab]` → run

### review

Читает конкретные файлы или diff и возвращает структурированный анализ — ничего не меняет.
Отличие от ask: агент читает код. Подходит для: "проверь этот файл", "найди проблемы в diff".

CLI: `code-scalpel review "..."`  
TUI hotkey: `[Tab]` → review

### learn *(v0.3+)*

Создать новый recipe или skill из знаний модели или URL документации.
В v0.1–v0.2 режим скрыт из TUI и недоступен в CLI.

CLI: `code-scalpel learn <name> [--url ...] [--type recipe|skill]`  
По умолчанию `--type recipe`. TUI hotkey: `[Tab]` → learn *(hidden until v0.3)*

### Как режимы связаны между собой

TUI открывается в `ask`. Пользователь может сразу набрать задачу или начать с обсуждения.

**Сценарий A — обсуждение → план → выполнение:**

```text
ask: "хочу добавить поиск, как лучше?"
  └─ агент читает INDEX/ARCH, отвечает
ask: "ок, через ripgrep, без векторов"
  └─ агент фиксирует решение
[Tab → plan]: "добавь поиск через ripgrep"
  └─ (предложено суммаризировать диалог перед переходом)
  └─ планировщик видит принятые решения, не переспрашивает
  └─ строит TASKS.md
[A] Run all → выполнение
```

**Сценарий B — прямо к делу:**

```text
[Tab → code]
"fix crash when query is empty"
  └─ классификатор: DEBUG, одноочевидная задача
  └─ агент: читает файлы → patch → apply → test
```

**Подсказки перехода** — агент предлагает сменить режим:

| Ситуация | Подсказка |
|---|---|
| В `ask`: пользователь говорит "давай сделаем" | `[P]lan first  [S]tep directly?` |
| В `code`: задача сложная, нет TASKS.md | `Looks complex. [P]lan first?` |
| В `plan`: TASKS.md готов | показывает Plan screen с `[R]/[A]` |
| Контекст `ask` > `compact_threshold` при переходе | предлагает суммаризировать |

**Carry-over: ask → plan**

Если в `ask` накопился диалог длиннее `compact_threshold`, при переключении в `plan`:

```text
┌─ Switch to plan? ──────────────────────────┐
│ Summarize discussion first?                │
│ 6.2k of context from ask session          │
│                                            │
│ [S] Summarize & plan   [F] Plan fresh      │
└────────────────────────────────────────────┘
```

`[S]` → compact суммаризирует диалог → суммари идёт в `stable_context` планировщика.
Планировщик не переспрашивает то что уже решили в `ask`.
Суммари сохраняется в `.code-scalpel/LAST_COMPACT.md`.

`[F]` → переходим в `plan` без контекста, агент спрашивает с нуля.

---

## 7. Model profiles

Именованные профили — быстрое переключение моделей без редактирования конфига.

```yaml
active_profile: local

profiles:
  local:
    provider: lmstudio
    model: qwen2.5-coder-14b-instruct
    # context_tokens: не задан → автодетект из GET /v1/models
    description: "Локальная, бесплатно, медленно"

  fast:
    provider: openrouter
    model: qwen/qwen-2.5-coder-32b-instruct
    # context_tokens: не задан → автодетект из GET /v1/models
    description: "Облако, быстро, дёшево"

  smart:
    provider: openrouter
    model: anthropic/claude-sonnet-4-5
    context_tokens: 200000   # override: у claude контекст больше чем репортит API
    description: "Лучшее качество, дороже"
```

**Автодетект `context_tokens`:** при старте агент делает `GET /v1/models`, берёт `context_length` активной модели.
Если API не возвращает — fallback на `context_tokens` из конфига. Если и его нет — ошибка с подсказкой прописать вручную.
Провайдеры, поддерживающие `context_length` в `/v1/models`: LM Studio, llama.cpp srv, vLLM, Ollama, OpenRouter.

Переключение:

```bash
code-scalpel --profile smart    # при запуске
code-scalpel profile smart      # сменить активный профиль
```

В TUI: `[m]` → SettingsCard появляется inline в потоке. Применяется немедленно, не попадает в контекст модели.

```text
  ╭─ settings ──────────────────────────────────╮   
  │ Profile  [>] local  [ ] fast  [ ] smart     │   
  │ Max files       [3]                         │   
  │ Max lines       [400]                       │   
  │ Ctx warn        [70%]                       │   
  ╰─────────────────────────────────────────────╯   
```

---

## 8. Конфигурация и секреты

### Иерархия (от низкого к высокому приоритету)

```text
~/.config/code-scalpel/config.yaml   # системные defaults
.code-scalpel/config.yaml                  # проектные overrides (только явно заданные ключи)
env vars / .env                       # секреты (наивысший приоритет)
```

Проектный конфиг не заменяет системный целиком — только перекрывает указанные ключи.  
Например, системный задаёт профили моделей, проектный — только `active_profile: smart`.

### Секреты

API-ключи никогда не хранятся в YAML. Только `.env` или переменные окружения:

```env
OPENROUTER_API_KEY=sk-or-...
OPENAI_API_KEY=sk-...
LMSTUDIO_API_KEY=lm-studio   # или пусто
```

```python
# config.py
from dotenv import load_dotenv
load_dotenv()
api_key = os.environ.get("OPENROUTER_API_KEY")
```

При `code-scalpel init` — автоматически добавить `.env` в `.gitignore`.

### Пример системного конфига

```yaml
# ~/.config/code-scalpel/config.yaml
language: en         # en | ru (v0.4)
active_profile: local

agent:
  llm_timeout: 120
  test_timeout: 60
  git_timeout: 10
  max_files: 3
  max_file_lines: 400
  max_debug_attempts: 2
  answer_reserve_tokens: 4000   # резерв под ответ модели
  context_budget_warn: 0.70     # порог жёлтого индикатора
  context_budget_critical: 0.90 # порог красного индикатора
  compact_threshold: 0.50       # порог появления [X] Compact в Q&A

profiles:
  local:
    provider: lmstudio
    model: qwen2.5-coder-14b-instruct
    context_tokens: 24000
  fast:
    provider: openrouter
    model: qwen/qwen-2.5-coder-32b-instruct
    context_tokens: 32000
  smart:
    provider: openrouter
    model: anthropic/claude-sonnet-4-5
    context_tokens: 200000
```

### Пример проектного конфига

```yaml
# .code-scalpel/config.yaml — только отличия от системного
active_profile: smart
agent:
  max_files: 5
```

---

## 9. Основной flow

```text
user task
  ↓
classify task (local heuristic)
  ↓
ask questions OR create plan (LLM)
  ↓
select next task
  ↓
collect minimal context
  ↓
generate patch (LLM, stream)
  ↓
extract diff from model output
  ↓
validate patch (git apply --check)
  ↓
show diff to user
  ↓
apply patch
  ↓
run tests
  ↓
summarize step → STATE.json
  ↓
continue or stop
```

---

## 10. Типы задач

```text
question / design / implement / debug / refactor / new_project
```

Определяются классификатором локально (без LLM) по тексту задачи.
`debug` — суб-режим внутри code/run, не отдельный TUI-режим.

---

## 11. TUI

### 11.1. Архитектура — один экран, inline-карточки

Нет отдельных Textual Screen-ов для patch/plan/tests.
Нет фиксированного хедера — бесконечный скролл сверху как в терминале.
Один экран, фиксированный низ:

```text
                                                     
  [бесконечный скролл вверх — вся история]          
                                                     
──────────────────────────────────────────────────── 
  last submitted message (highlighted bg)            
──────────────────────────────────────────────────── 
  mode › input (multiline) или hint пока думает      
──────────────────────────────────────────────────── 
  footer: key hints · статус · ctx · токены          
```

Режим показывается как префикс ввода: `ask ›`, `code ›`, `plan ›`, `run ›`.
Карточки (patch, plan, Q&A, tests) рендерятся inline в поток — не отдельные экраны.
Footer: только ключевые хинты + статус + токены. Режим — не в footer.

### 11.2. Виджеты

RichLog не справится с интерактивными карточками — нужны кастомные Textual-виджеты.

```text
tui/
  app.py              # App + единственный Screen
  styles.tcss         # глобальная CSS
  widgets/
    output.py         # OutputLog — scrollable content area
    input.py          # ModeInput + HistoryInput (bash-style ↑/↓ history)
    footer.py         # StatusFooter — key hints + статус + ctx + модель
    jobs_bar.py       # JobsBar — inline «⚙ N jobs: kind1 · kind2», прячется при idle
    jobs_modal.py     # JobsModal — Ctrl+J: список всех jobs с описаниями и возрастом
    plan_card.py      # PlanCard — inline список T-задач из TASKS.md
    tool_use.py       # ToolUseCard — collapsible inline-карточка read_file/grep/map_file и др.
    tool_result_modal.py  # ToolResultModal — Ctrl+O: full view последнего tool-result
    turn_progress.py  # TurnProgress — live tokens/sec + tool count во время стрима
    _map_highlight.py # подсветка project_map в модалке без Pygments
    cards/
      tool_call.py    # ToolCallCard — диф + [a]/[r]/[g] для apply-flow
```

`OutputLog` умеет монтировать виджеты-карточки inline наравне с текстом.
Когда карточка готова — добавляется через `output.add_*`, появляется в потоке.
После завершения карточки (apply/reject/confirm) — она становится read-only в истории.

Слэш-команды (v0.3): `/new`, `/compact`, `/map`, `/tasks`, `/stats`,
`/remember`, `/recall`, `/loop`, `/run`, `/help`, `/mode <name>`.
Хоткеи: `Ctrl+T` — переключить режим, `Ctrl+O` — last tool result modal,
`Ctrl+J` — jobs modal, `Ctrl+↑/↓` — навигация по tool-карточкам, `Esc` —
отмена / возврат в инпут, `↑/↓` в инпуте — bash history.

### 11.3. Idle

```text
                                                     
                                                     
──────────────────────────────────────────────────── 
 ask › _                                             
──────────────────────────────────────────────────── 
 [tab] mode · [m] model · [q] quit · ● idle · 0k/24k · $0.00
```

### 11.4. Ask — стриминг

```text
   Two options for notes-app:                        
                                                     
   1. ripgrep — fast, already a dep                  
   2. sqlite FTS — only if you migrate to sqlite     
                                                     
   INDEX shows JSON storage. Recommend ripgrep. ◌    
──────────────────────────────────────────────────── 
 > как лучше добавить поиск?                         
──────────────────────────────────────────────────── 
 ask › _                                             
──────────────────────────────────────────────────── 
 * Parsing… (8s · working) · esc to interrupt · 4k/24k · 1.2k in
```

Input **никогда не блокируется** — можно набирать следующее пока модель думает.
Напечатанное встаёт в очередь. Очередь показывается вертикально со стрелкой `>` перед каждым сообщением.
Хинт под инпутом: `Press up to edit queued messages`. `↑` → редактировать очередь.

Статус в footer пока работает:
```text
* Generating… (44s · ↓ 1.6k tokens · thought for 7s)
```
- Глагол ротируется: Reading, Analyzing, Generating, Writing, Reasoning…
- `↓ Nk tokens` — полученные completion tokens
- `thought for Ns` — время reasoning (если модель поддерживает)
- `esc to interrupt` добавляется справа

По завершении:
```text
* Worked for 1m 17s
```

`[Esc]` прерывает Worker не трогая input.

### 11.5. Ask — transition hint после ответа

```text
   INDEX shows JSON storage. Recommend ripgrep.      
                                                     
   Ready. Switch to plan or code to start.           
   [p] plan   [c] code directly                     
                                                     
──────────────────────────────────────────────────── 
 > окей, делаем через ripgrep                        
──────────────────────────────────────────────────── 
 ask › _                                             
──────────────────────────────────────────────────── 
 [tab] mode · [x] compact · [q] quit · ● idle · 5k/24k · 1.9k in · $0.00
```

### 11.6. Step — inline PatchCard

```text
   ◌ reading src/notes.py                           
   ◌ generating patch...                             
                                                     
  ╭─ patch · src/notes.py ──────────────────────╮   
  │ - def search_notes(query):                  │   
  │ + def search_notes(query: str = ""):        │   
  │ +     if not query:                         │   
  │ +         return list_notes()               │   
  ╰─────────────────────────────────────────────╯   
                                                     
──────────────────────────────────────────────────── 
 > fix crash when search query is empty              
──────────────────────────────────────────────────── 
 code › _                                            
──────────────────────────────────────────────────── 
 [a] apply · [r] reject · [g] regen · ◌ reviewing · 4.8k in
```

### 11.7. После apply — inline TestsCard

```text
  ╭─ patch · src/notes.py ──────────────────────╮   
  │ ✓ applied                                   │   
  ╰─────────────────────────────────────────────╯   
  ╭─ tests · pytest tests/ ─────────────────────╮   
  │ ✓ 5 passed in 0.6s                          │   
  ╰─────────────────────────────────────────────╯   
   Done. [n] next task · [q] stop                   
──────────────────────────────────────────────────── 
 code › _                                            
──────────────────────────────────────────────────── 
 [n] next · [q] stop · ● idle · 9k/24k · 6.1k in · $0.00
```

### 11.8. Plan — inline PlanCard

Шаги отмечаются в реальном времени по мере выполнения — `[ ]` → `[✓]` прямо в карточке.
Текущий шаг выделен цветом (`--accent`). Выполненные — dimmed.

```text
  ╭─ plan ──────────────────────────────────────╮   
  │ [✓] T001 Add search_notes()                 │   
  │ [✓] T002 Handle empty query                 │   
  │ [ ] T003 Add tests                          │   
  │ [ ] T004 Update README                      │   
  ╰─────────────────────────────────────────────╯   
──────────────────────────────────────────────────── 
 plan › _                                            
──────────────────────────────────────────────────── 
 [r] run · [e] edit · [esc] back
```

`[✓]` — зелёный, выполненные dimmed. Текущий шаг — строка подсвечена `--accent`. Три хоткея, не пять.

### 11.9. Tool calls — inline ToolCallCard

Каждый вызов инструмента (read, search, git, ripgrep) показывается как свёрнутая строка.
Раскрывается по `ctrl+o` — показывает полный вывод в карточке. Повторный `ctrl+o` — сворачивает.

Формат — как в Claude Code: заголовок с bullet, сводка через `└`, детали ниже.

**Running:**
```text
 ◌ Read(src/notes.py)
```

**Success — короткий вывод (показывается сразу):**
```text
 ● Read(src/notes.py)
 └ 43 lines
```

**Success — Write/Create с превью:**
```text
 ● Write(CLAUDE.md)
 └ Wrote 58 lines to CLAUDE.md
      2  # code-scalpel
      3  TUI coding agent...
      … +53 lines (ctrl+o to expand)
```

**Success — diff (патч, всегда виден):**
```text
 ● Apply(src/notes.py)
 └ Added 4 lines, removed 1 line
    14  - def search_notes(query):
    14  + def search_notes(query: str = ""):
    15  +     if not query:
    16  +         return list_notes()
```

**Success — длинный вывод (свёрнут, ctrl+o раскрывает):**
```text
 ● Search("def search")
 └ 12 matches in 3 files  ▸ ctrl+o to expand
```

**Error** (кружок — `--diff-del` красный):
```text
 ● Apply(src/notes.py)
 └ Error: patch does not apply
    error: patch failed: src/notes.py:14
    error: src/notes.py: patch does not apply
```

Цвет кружка: `◌` серый (running) → `●` зелёный (success) → `●` красный (error).

Ошибки inline — никаких попапов. Агент читает вывод и решает что делать дальше.
Длинный вывод обрезается до 10 строк с пометкой `(N lines total · ctrl+o to expand)`.

**Скиллы при старте сессии** — одна строка в поток:

```text
   ✓ skills: python (pytest, ruff) · docker       
```

Если скиллов нет: `  ✓ skills: none detected`.

### 11.10. Q&A — inline QACard

```text
  ╭─ clarify ───────────────────────────── 38% ─╮   
  │ 1. Where to store users?                    │   
  │    [>] SQLite  [ ] JSON  [ ] In-memory      │   
  │ 2. Auth type?                               │   
  │    [>] Token   [ ] Session  [ ] JWT         │   
  ╰─────────────────────────────────────────────╯   
──────────────────────────────────────────────────── 
 plan › _                                            
──────────────────────────────────────────────────── 
 [enter] confirm · [e] edit · [x] compact · [esc] cancel
```

`[x] compact` появляется когда ctx > `compact_threshold`.

### 11.11. UX-требования

**Никаких попапов и модальных диалогов.** Всё — inline карточки в потоке.
Это включает: настройки (`[m]`), profile picker, resume, compact-предложение, ошибки.

**Мышь и копирование:**
Весь текст в OutputLog выделяется мышью и копируется стандартным способом терминала.
Карточки не перехватывают mouse events — только keyboard shortcuts.
Реализация: `can_focus = False` на read-only частях; не переопределять `on_mouse_*` где не нужно.

**Клавиши:**
- `ctrl+o` — expand/collapse последнего ToolCallCard
- `[esc]` — закрыть активную карточку / прервать Worker
- `[q]` — выход (только из idle)
- `[m]` — открыть SettingsCard inline
- `↑` в пустом инпуте — редактировать очередь сообщений

### 11.12. Цветовая схема

Вдохновение — Claude Code: тёмный фон, cyan-акценты.

```css
/* tui/theme.tcss — единственное место для цветов */
/* Вдохновение: Claude Code color scheme */
:root {
    --bg: #0f0f0f;        --bg-panel: #1c1c1c;
    --fg: #d0d0d0;        --fg-dim: #585858;   --fg-muted: #3a3a3a;
    --border: #2a2a2a;
    --accent: #00d7ff;    /* cyan — режимы, ссылки, active elements */
    --thinking: #ff8700;  /* amber — спиннер, >> курсор, "thinking" состояние */
    --success: #00ff87;   --error: #ff5555;    --warning: #ffb86c;
    --diff-add: #50fa7b;  --diff-add-bg: #0a2a0a;  /* текст и фон добавленных строк */
    --diff-del: #ff5555;  --diff-del-bg: #2a0a0a;  /* текст и фон удалённых строк */
    --line-num: #3a3a3a;  /* номера строк в diff */
}
```

```css
/* tui/styles.tcss — структура без хардкода цветов */
Screen        { background: $bg; color: $fg; }
Header        { background: $bg-panel; color: $accent; text-style: bold; }
Footer        { background: $bg-panel; color: $fg-dim; }
.prompt       { color: $thinking; }         /* >> курсор ввода */
.thinking     { color: $thinking; }         /* спиннер, "Discombobulating…" */
.dim          { color: $fg-dim; }           /* "Brewed for 47s" */
.success      { color: $success; }          .error { color: $error; }
.diff-add     { color: $diff-add; background: $diff-add-bg; }
.diff-del     { color: $diff-del; background: $diff-del-bg; }
.line-num     { color: $line-num; }
```

UI-консистентность: единый layout (header / content / keys / statusbar).
`[Esc]` — назад/отмена везде. `[Q]` — выход. `[Tab]` — режим.

---

## 12. Команды CLI

```bash
code-scalpel init               # .code-scalpel/ + INDEX.json
code-scalpel                    # открыть TUI
code-scalpel ask "..."          # быстрый вопрос
code-scalpel plan "..."         # построить план
code-scalpel code               # один шаг (manual)
code-scalpel run                # supervised autonomous
code-scalpel review "..."       # read-only анализ
code-scalpel learn <name>                      # создать recipe (по умолчанию)
code-scalpel learn <name> --type skill        # создать skill
code-scalpel learn <name> --url <url>         # из документации URL
code-scalpel recipes                          # список активных recipes
code-scalpel skills                           # список активных skills
code-scalpel profile <name>     # сменить активный профиль
code-scalpel --profile <name>   # запустить с профилем
code-scalpel resume             # возобновить прерванную сессию
code-scalpel compact            # сжать историю Q&A (только внутри TUI, см. 19.4)
code-scalpel status             # STATE.json
code-scalpel index              # пересобрать INDEX.json
code-scalpel config             # открыть конфиг
```

### init

```text
1. mkdir .code-scalpel/
2. list_files (pathspec + .gitignore)
3. AST-символы каждого файла → INDEX.json (без LLM)
4. STATE.json с дефолтами
5. пустые TASKS.md, ARCH.md, DECISIONS.md
```

LLM-summaries в INDEX.json — только при явном флаге `--summarize` или в профилях `fast`/`smart`.
По умолчанию: путь + символы + imports. Этого достаточно для context builder на слабой модели.

`ARCH.md` и `DECISIONS.md` — заполняет пользователь вручную.
Агент читает как stable context, не пишет.

---

## 13. Структура проекта

```text
code_scalpel/
  app.py              # Textual Application + composition root
  cli.py              # Typer CLI
  config.py           # YAML + pydantic

  llm/
    base.py                  # LLMAdapter Protocol + ChatResponse
    openai_compatible.py     # все OpenAI-совместимые провайдеры

  core/
    classifier.py     # local heuristic: текст → TaskType (pure function)
    planner.py        # LLM → TASKS.md
    executor.py       # тонкий координатор: run_plan() loop + stop conditions
    step.py           # один шаг: context→LLM→extract→validate→apply→test→summarize
    context/
      builder.py      # сборка messages[]: system+mode+stable+anchor+dynamic
      budget.py       # подсчёт токенов + стратегии компрессии
    summarizer.py     # summary шага / файла / сессии (LLM или template)
    index.py          # INDEX.json: build, update, query
    state.py          # STATE.json r/w, атомарная запись (write tmp → rename)
    session.py        # Session stats (токены, cost, время)

  tools/
    shell.py          # ShellRunner Protocol + AsyncShellRunner (whitelist)
    files.py          # list_files, read_file
    search.py         # ripgrep
    git.py            # diff, status, apply, rollback
    tests.py          # run_tests, parse output

  patch/
    parser.py         # unified diff из текста модели (pure)
    validator.py      # git apply --check
    applier.py        # git apply + rollback

  skills/
    base.py           # Skill + Tool + ToolParam dataclasses, Protocols
    registry.py       # SkillRegistry + ToolRegistry
    loader.py         # загрузка .md и .py из директорий
    lang/
      python.py       # ast extractor + pytest/ruff/mypy    ← MVP
      javascript.py   # regex extractor + jest/eslint       ← v0.4
      go.py           # go test/fmt                         ← v0.4
      rust.py         # cargo test/clippy                   ← v0.4
    comp/
      docker.md       # docker compose, Dockerfile          ← v0.3

  tui/
    theme.tcss        # только переменные цветов
    styles.tcss       # структура (использует переменные)
    messages.py       # Textual Message классы
    app.py            # App + единственный Screen
    widgets/
      output.py       # OutputLog — scrollable content + mount_card()
      input.py        # ModeInput — multiline, mode-префикс (ask ›)
      footer.py       # StatusFooter — key hints + статус + ctx + токены
      cards/
        tool_call.py  # ToolCallCard — все вызовы инструментов:
                      #   read, search, git, ripgrep  → read-only сразу
                      #   apply (reviewing phase)     → diff + [a]/[r]/[g]
                      #   apply (done)                → read-only результат
                      #   run pytest                  → output + [n]/[q]
        plan.py       # PlanCard — task list + [r]/[a]/[e]
        form.py       # FormCard — любая форма с полями/вариантами:
                      #   QA clarification  → радиокнопки + [enter]/[x compact]
                      #   Settings          → редактируемые поля + [enter]/[esc]
        choice.py     # ChoiceCard — бинарный выбор из 2-3 вариантов:
                      #   Resume            → [c] continue / [r] restart
                      #   Compact offer     → [s] summarize / [f] plan fresh

  prompts/
    system.md         # всегда, статичный
    planner.md        # режим plan
    executor.md       # режимы code + run + few-shot diff
    debugger.md       # суб-шаг debug
    reviewer.md       # режим review
    summarizer.md     # summary шага/файла через LLM
    recipe_creator.md # learn --type recipe (по умолчанию)
    skill_creator.md  # learn --type skill

tests/
  conftest.py
  mocks.py
  unit/
    test_classifier.py
    test_parser.py
    test_context_builder.py
    test_budget.py
    test_step.py
    test_summarizer.py
    test_validator.py
    test_applier.py
    test_state.py
    test_skill_loader.py
  integration/
    test_executor.py
  tui/
    test_output.py       # OutputLog + mount_card
    test_tool_call.py    # ToolCallCard: все фазы (running/done/error/reviewing/apply)
    test_form_card.py    # FormCard: QA-режим и settings-режим
    test_choice_card.py  # ChoiceCard: resume и compact-offer
```

---

## 14. Рабочая директория агента

```text
.code-scalpel/
  STATE.json          # текущее состояние агента
  TASKS.md            # план задач
  ARCH.md             # архитектура (пишет пользователь)
  DECISIONS.md        # решения (пишет пользователь)
  INDEX.json          # индекс файлов + summaries
  LAST_CONTEXT.md     # stable_context последнего запроса (для дебага)
  LAST_DIFF.patch     # последний patch
  LAST_TEST.txt       # вывод последних тестов
  LAST_COMPACT.md     # compact-summary последнего сжатия (для дебага)
  SESSION.md          # итоговый summary сессии (пишется при выходе)
  skills/             # project-local skills (.md)
```

---

## 15. Пример TASKS.md

```md
## T001: Add note search

Status: done
Summary: Added search_notes() in src/notes.py, 3 tests pass.

Goal: Add search_notes(query: str) -> list[Note].
Files: src/notes.py, tests/test_notes.py
Acceptance:
- Search by title and body, case-insensitive
- Empty query returns all notes
- Tests pass
Test command: pytest tests/test_notes.py
```

---

## 16. Пример STATE.json

```json
{
  "current_task": "T002",
  "step_phase": "testing",
  "dirty_patch": true,
  "mode": "run",
  "profile": "local",
  "context_limit": 24000,
  "max_files": 3,
  "max_file_lines": 400,
  "last_test_status": "passed",
  "debug_attempts": 0,
  "completed_tasks": ["T001"],
  "last_saved_at": "2025-05-10T14:32:11"
}
```

`step_phase`: `idle | generating | reviewing | applying | testing`  
`dirty_patch`: патч применён, тесты ещё не прошли — нужна страховка при краше.  
Запись атомарная: `write .code-scalpel/STATE.tmp → rename STATE.json`.

---

## 17. Пример INDEX.json

```json
{
  "files": [
    {
      "path": "src/notes.py",
      "summary": "Note model and CRUD: add, list, delete notes to JSON file",
      "symbols": ["class Note", "def add_note", "def list_notes"],
      "imports": ["json", "pathlib"],
      "tests": ["tests/test_notes.py"],
      "summarized_at": "2025-05-10T12:00:00"
    }
  ]
}
```

`summary` генерируется LLM при `init --summarize` / `index --summarize`. Обновляется при изменении файла.
По умолчанию `summary` — AST-символы + imports (без LLM).
В контекст попадают только релевантные записи (по символам/именам файлов из задачи).

---

## 18. LLM адаптер

```python
@dataclass
class ChatResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    cost: float | None

class LLMAdapter(Protocol):
    async def chat(self, messages: list[dict], **kwargs) -> ChatResponse: ...
    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]: ...
```

`chat()` — для коротких запросов (summarize, classify).
`stream()` — для TUI (показываем токены в реальном времени).

```python
class OpenAICompatibleAdapter:
    def __init__(self, base_url, api_key, model, cost_per_1k=None): ...

    async def chat(self, messages, **kwargs) -> ChatResponse:
        response = await self.client.chat.completions.create(...)
        return ChatResponse(
            content=response.choices[0].message.content,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            cost=self._calc_cost(response.usage),
        )

    async def stream(self, messages, **kwargs) -> AsyncIterator[str]:
        async with self.client.chat.completions.stream(...) as s:
            async for event in s:
                if event.type == "content.delta":
                    yield event.delta

    def _calc_cost(self, usage) -> float | None:
        if hasattr(usage, "cost") and usage.cost is not None:
            return usage.cost     # OpenRouter возвращает напрямую
        if self.cost_per_1k:
            return (usage.prompt_tokens * self.cost_per_1k["input"] / 1000
                    + usage.completion_tokens * self.cost_per_1k["output"] / 1000)
        return None
```

Конфиг провайдеров — в разделе 7 (profiles).

---

## 19. Суммаризация контекста

Ключевой механизм для работы в рамках ограниченного контекста модели.
Пять сценариев, все через `core/summarizer.py`.

### 19.1. Summary шага

После каждого выполненного шага — 1–3 строки что было сделано.
Записывается в `TASKS.md` (поле `Summary`) и `STATE.json`.

**Когда использовать LLM:** профиль с большим контекстом (smart/fast).
**Когда template:** слабая локальная модель — не тратить токены.

```python
async def summarize_step(result: StepResult, llm: LLMAdapter | None) -> str:
    if llm and result.mode != "local_weak":
        return await _llm_summary(result, llm)
    return _template_summary(result)   # "Applied patch to {files}. Tests: {status}."
```

---

### 19.2. Summary файла для INDEX

При `init --summarize` и `index --summarize` — краткое описание каждого файла (1–2 строки) через LLM.
Включается только при явном флаге или в профилях `fast`/`smart`.

По умолчанию (в т.ч. на локальной слабой модели): путь + AST-символы + imports — этого достаточно
для context builder чтобы выбирать релевантные файлы.

```python
async def summarize_file(path: Path, source: str, llm: LLMAdapter | None) -> str:
    if llm is None:
        return _ast_summary(path, source)  # символы + imports, без LLM
    # промт: "Describe in 1-2 sentences what this file does"
    return await _llm_summary(source, llm)
```

Промт: `prompts/summarizer.md`.

---

### 19.3. Компрессия контекста при переполнении

Если `dynamic_context` не вмещается в бюджет — сжать.

```text
Приоритет сжатия (от низкого к высокому — что сжимать первым):
1. file index → оставить только релевантные записи
2. code snippets → обрезать до первых N строк + показать символы
3. test output → оставить только traceback (убрать прошедшие тесты)
4. git diff → оставить только изменённые функции (trim context lines)
```

Если после сжатия всё ещё не влезает — `StopCondition(context_budget_exceeded)`.
LLM-based сжатие (суммаризировать код блоками) — только в профилях с 32k+ контекстом.

---

### 19.4. Compact

Compact сжимает текущий диалог (Q&A или затянувшийся plan) до краткого summary.
Не трогает уже выполненные шаги — только активный контекст.

**Когда нужен:**
- Q&A-диалог занял > 50% бюджета
- Пользователь нажал `[X]` в Q&A-экране или вызвал `code-scalpel compact`

**Что делает:**
```text
1. взять messages[] текущего диалога
2. LLM: "Summarize this Q&A into key decisions in 5-10 lines"
3. заменить messages[] на [system, mode, compact_summary]
4. продолжить с освобождённым бюджетом
```

Compact-summary сохраняется в `.code-scalpel/LAST_COMPACT.md` для дебага.

Если LLM недоступна (локальная модель упала) — template-fallback:
собрать выбранные пользователем ответы из Q&A в виде bullet-list.

---

### 19.5. Session summary при выходе

При `[Q]` / завершении сессии — записать `SESSION.md`:

```text
Session: 2025-05-10 14:30 — 15:05
Profile: local (qwen14b)
Tasks completed: T001, T002, T003
Tokens: 45 231 in / 8 441 out
Cost: $0.00

## T001: Added search_notes()
## T002: Fixed empty query bug
## T003: Added 5 tests
```

Template-based для слабых моделей. LLM-based (связный текст) для strong профилей.

---

## 20. Структура промтов

### Сборка сообщений (кэш-friendly)

```text
[system.md]        ← всегда, строго статичный (в KV-кэше)
[{mode}.md]        ← зависит от режима (в KV-кэше — меняется только при смене режима)
[stable_context]   ← ARCH.md + INDEX summary + skill snippets (в KV-кэше)
[assistant: OK]    ← якорь, стабилизирует prefix
[dynamic_context]  ← задача + файлы шага + traceback + diff
```

Только `dynamic` блок меняется на каждом шаге.

`LAST_CONTEXT.md` = сохранённый `stable_context` последнего запроса для дебага.

### Матчинг режимов и промтов

| Режим | Промты |
|---|---|
| `ask` | `system.md` + `stable_context` (INDEX metadata, ARCH.md, DECISIONS.md — без сырых файлов) |
| `plan` | `system.md` + `planner.md` |
| `code` / `run` | `system.md` + `executor.md` |
| `review` | `system.md` + `reviewer.md` |
| `learn --type recipe` | `system.md` + `recipe_creator.md` |
| `learn --type skill` | `system.md` + `skill_creator.md` |
| debug sub-mode | `system.md` + `executor.md` + `debugger.md` |
| summarize | `summarizer.md` (отдельный вызов, без system) |

`code` и `run` — один промт, разница в поведении executor (пауза на подтверждение).

### Промт-файлы

| Файл | Что содержит |
|---|---|
| `system.md` | роль, правила, формат — никакой динамики |
| `planner.md` | как строить TASKS.md с acceptance criteria |
| `executor.md` | инструкции + few-shot пример diff |
| `debugger.md` | traceback → гипотеза → minimal fix |
| `reviewer.md` | read-only анализ: объяснение, риски, предложения |
| `summarizer.md` | 1–3 строки summary шага или файла |
| `skill_creator.md` | генерация Markdown-скилла с frontmatter |

---

## 21. Классификатор задач

`core/classifier.py` — локальная эвристика, pure function, без LLM.

```python
def classify(task: str) -> TaskType:
    t = task.lower()
    if any(w in t for w in ("fix", "bug", "error", "traceback", "fails")):
        return TaskType.DEBUG
    if any(w in t for w in ("explain", "what", "how", "why", "describe")):
        return TaskType.QUESTION
    if any(w in t for w in ("refactor", "rename", "move", "restructure")):
        return TaskType.REFACTOR
    if any(w in t for w in ("add", "implement", "create", "write")):
        return TaskType.IMPLEMENT if len(task) < 60 else TaskType.DESIGN
    return TaskType.DESIGN
```

---

## 22. Recipes и Skills — plugin-система

### Идея

Без изменения кода приложения: добавил файл → агент умеет больше.
Два типа, каждый решает разную задачу.

### Recipe — знание о технологии

Что существует в проекте: язык, инструменты, компоненты.
Содержит: команды запуска тестов/линтера, whitelist команд, snippets для контекста.

```text
load: eager  → язык проекта (Python, TypeScript…) + core tools (ruff, pytest…)
               загружается один раз в stable_context при старте сессии
load: lazy   → компоненты (Docker, PostgreSQL, Redis…)
               загружается в dynamic_context только для шагов плана,
               где keywords совпадают с описанием шага
```

Пример: проект с Python + Docker. При старте → python.md в stable context.
Шаг "deploy to docker" → docker.md добавляется только на этот шаг, потом выгружается.

**Recipe (Markdown):**

```markdown
---
name: python
load: eager
file_patterns: ["*.py", "pyproject.toml"]
test_cmd: ["pytest", "-x"]
lint_cmds: [["ruff", "check", "."], ["mypy", "."]]
allowed_commands: ["pytest", "ruff", "mypy", "python", "python3"]
symbol_extractor: ast
---

# Python
- Типизируй всё: аннотации на всех публичных функциях и методах
- Запуск тестов: `pytest -x` (стоп на первом падении)
- Линтер: `ruff check --fix . && ruff format .`
- Никаких `# type: ignore` без крайней необходимости
```

```markdown
---
name: docker
load: lazy
file_patterns: ["Dockerfile", "docker-compose.yml", "compose.yml"]
keywords: ["docker", "compose", "container", "image", "deploy"]
allowed_commands: ["docker", "docker compose"]
---

# Docker
- `docker compose up -d` / `docker compose logs -f`
- Layer caching: COPY зависимости до COPY кода
- `docker compose ps` — статус сервисов
```

### Skill — инструкция к задаче

Что делать сейчас: как добавить тест, как отладить патч, как рефакторить.
Чистый Markdown, никаких команд. Загружается в dynamic_context на время задачи.

```markdown
---
name: add_tests
triggers: ["add test", "write test", "test coverage", "тест"]
---

# Добавление тестов
1. Определи что тестируем: happy path, edge case, error path
2. Используй MockLLMAdapter / MockShellRunner из tests/mocks.py
3. Один assert на тест — понятные падения
4. Имя теста = что должно произойти: `test_returns_none_when_empty`
```

### Dataclasses

```python
@dataclass
class Recipe:
    name: str
    load: Literal["eager", "lazy"]
    file_patterns: list[str]
    keywords: list[str] = field(default_factory=list)   # для lazy-matching
    test_cmd: list[str] | None = None
    lint_cmds: list[list[str]] = field(default_factory=list)
    allowed_commands: list[str] = field(default_factory=list)
    symbol_extractor: str | None = None                 # "ast" | "regex:<pattern>"
    body: str = ""                                      # текст после frontmatter

@dataclass
class Skill:
    name: str
    triggers: list[str]                                 # keywords для автоматической активации
    body: str
```

### Директории discovery

```text
code_scalpel/recipes/*.md         # встроенные рецепты (python, git, pytest…)
code_scalpel/skills/*.md          # встроенные скиллы (add_tests, debug_patch…)
~/.config/code-scalpel/recipes/   # пользовательские рецепты
~/.config/code-scalpel/skills/    # пользовательские скиллы
.code-scalpel/recipes/            # project-local (приоритет выше)
.code-scalpel/skills/
```

Registry сканирует при старте. project > user > builtin.

### Команда learn

```bash
code-scalpel learn redis           # создать recipe
code-scalpel learn add_tests       # создать skill
code-scalpel learn nginx --url https://nginx.org/en/docs/
```

Flow: `recipe_creator.md` / `skill_creator.md` → LLM генерирует → preview → `[A]ccept [E]dit [R]eject` → сохранить.

**Что можно писать в каждом типе** (промты `*_creator.md` это явно запрещают):

| | Recipe | Skill |
|---|---|---|
| Команды запуска тестов/линтера | ✓ | — |
| Конвенции технологии | ✓ | — |
| Whitelist команд | ✓ | — |
| Пошаговый подход к задаче | — | ✓ |
| Как думает агент | — | — |
| Формат патча | — | — |
| Поведение агента | — | — |

Последние три строки — зона `prompts/`. Ни recipe, ни skill туда не заходят.

### Интеграция с контекстом

```python
# При старте сессии:
eager_recipes = [r for r in registry.recipes if r.load == "eager" and matches_project(r)]
stable_context += [r.body for r in eager_recipes]

# При запуске шага плана:
step_recipes = [r for r in registry.recipes
                if r.load == "lazy" and any(kw in step.description for kw in r.keywords)]
step_skills  = [s for s in registry.skills
                if any(tr in task.description for tr in s.triggers)]
dynamic_context += [r.body for r in step_recipes] + [s.body for s in step_skills]

# Команды для whitelist:
allowed = GLOBAL_WHITELIST | {c for r in active_recipes for c in r.allowed_commands}
# Команды тестов:
test_cmd = next((r.test_cmd for r in eager_recipes if r.test_cmd), None)
```

---

## 23. ShellRunner

```python
class ShellResult(NamedTuple):
    output: str
    returncode: int

class ShellRunner(Protocol):
    async def run(self, cmd: list[str], timeout: int = 30) -> ShellResult: ...

class AsyncShellRunner:
    async def run(self, cmd, timeout=30) -> ShellResult:
        self._check_whitelist(cmd)
        proc = await asyncio.create_subprocess_exec(*cmd, ...)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return ShellResult(stdout.decode(), proc.returncode)
```

Все модули (`git.py`, `tests.py`, `search.py`, `validator.py`, `applier.py`) получают `ShellRunner` через конструктор.

---

## 24. Async-архитектура и UX

TUI не замирает никогда. Все блокирующие операции — в Textual Workers.

```text
event loop
  ├── Worker: LLM streaming   ← llm.stream(), exclusive=True
  ├── Worker: subprocess      ← AsyncShellRunner
  └── file I/O                ← asyncio.to_thread(path.read_text)
```

**Состояния:**

```text
IDLE → THINKING → STREAMING → REVIEWING → APPLYING → TESTING → DONE → ERROR
```

**LLM worker:**

```python
@work(exclusive=True)
async def run_llm_stream(self, messages):
    try:
        collected = []
        async for token in self.llm.stream(messages):
            collected.append(token)
            self.post_message(TokenReceived(token))
        self.post_message(LLMDone("".join(collected)))
    except asyncio.CancelledError:
        self.post_message(LLMCancelled())
    except Exception as e:
        self.post_message(LLMError(str(e)))
```

**Messages (tui/messages.py):**

```python
class TokenReceived(Message): token: str
class LLMDone(Message): content: str
class LLMCancelled(Message): pass
class LLMError(Message): error: str
class SubprocessDone(Message): output: str; returncode: int
class SubprocessTimeout(Message): cmd: list[str]
```

**Таймауты:**

```yaml
agent:
  llm_timeout: 120
  test_timeout: 60
  git_timeout: 10
```

`[Esc]` отменяет текущий Worker в любой момент.

**Session end:** при `[Q]` — сохранить STATE.json + записать SESSION.md.

**Атомарные сохранения STATE.json:** после каждого значимого действия (patch applied, tests ran, task done, mode changed). Запись через tmp-файл → rename, чтобы краш не оставил битый JSON.

---

## 25. Тестирование

DI через конструктор везде. `app.py` — единственный composition root.

**Протоколы:**

```python
class LLMAdapter(Protocol):   # llm/base.py
    async def chat(...) -> ChatResponse: ...
    async def stream(...) -> AsyncIterator[str]: ...

class ShellRunner(Protocol):  # tools/shell.py
    async def run(...) -> ShellResult: ...
```

**Моки (tests/mocks.py):**

```python
class MockLLMAdapter:
    calls: list[list[dict]] = []

    async def chat(self, messages, **kwargs) -> ChatResponse:
        self.calls.append(messages)
        return ChatResponse(next(self._responses), 100, 50, None)

    async def stream(self, messages, **kwargs) -> AsyncIterator[str]:
        self.calls.append(messages)
        for token in next(self._responses).split():
            yield token + " "

class MockShellRunner:
    calls: list[list[str]] = []

    def register(self, cmd, result): ...
    async def run(self, cmd, timeout=30) -> ShellResult: ...
```

**Слои:**

| Модуль | Мок |
|---|---|
| `patch/parser.py` | нет (pure) |
| `core/classifier.py` | нет (pure) |
| `core/summarizer.py` | MockLLMAdapter |
| `patch/validator.py` | MockShellRunner |
| `tools/git.py` | MockShellRunner |
| `core/context.py` | tmp_path + mock index |
| `core/index.py` | MockLLMAdapter + tmp_path |
| TUI screens | Textual Pilot |

**Integration test:**

```python
async def test_implement_step(tmp_path, agent_dir, sample_project):
    llm = MockLLMAdapter(responses=[VALID_DIFF, "Added search_notes()."])
    shell = MockShellRunner()
    shell.register(["git", "apply", "--check", ...], ShellResult("", 0))
    shell.register(["git", "apply", ...], ShellResult("", 0))
    shell.register(["pytest", "tests/"], ShellResult("1 passed", 0))

    executor = Executor(llm=llm, shell=shell, root=tmp_path)
    result = await executor.step(task=SAMPLE_TASK)

    assert result.status == "done"
    assert "search_notes" in (tmp_path / "src/notes.py").read_text()
```

**TUI:**

```python
async def test_patch_screen(tmp_path):
    app = CodeScalpelApp(llm=MockLLMAdapter([VALID_DIFF]), shell=MockShellRunner())
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.wait_for_animation()
        await pilot.press("a")   # apply
        assert app.query_one("#status").has_class("success")
```

---

## 26. Управление контекстом

### Бюджет

`context_tokens` берётся из автодетекта `/v1/models` или override в конфиге профиля.
`answer_reserve_tokens` задаётся в конфиге агента (default: 4000).

```text
[system.md]             1–2k   в KV-кэше
[mode.md]               0.5–2k в KV-кэше
[stable_context]        2–8k   в KV-кэше
  └ ARCH.md + INDEX summary + skill snippets
[dynamic_context]       меняется каждый шаг:
  current task          1–2k
  code snippets         6–16k
  test output           1–4k
  git diff              1–3k
[answer reserve]        config: answer_reserve_tokens
```

Бюджет dynamic_context = `context_tokens` − static_parts − `answer_reserve_tokens`.
Все числа из конфига, нет хардкода.

### Компрессия при переполнении

```text
1. file index       → только совпадающие с задачей
2. code snippets    → обрезать до N строк, добавить список символов
3. test output      → только traceback, убрать passed
4. git diff         → только diff без context lines
→ если не помогло: StopCondition(context_budget_exceeded)
```

### Правила для слабых моделей

```text
max_files: 3       max_file_lines: 400
max_patch_files: 3   one task per step
```

---

## 27. Patch workflow

**Извлечение (parser.py — pure):**

```text
1. найти ```diff...``` или "diff --git"
2. unidiff → validate
3. None → caller делает retry (до 2 раз с явным форматом)
4. после 2 retry None → StopCondition(diff_extraction_failed)
```

**Применение:**

```bash
git apply --check .code-scalpel/LAST_DIFF.patch
git apply .code-scalpel/LAST_DIFF.patch
git apply --reverse .code-scalpel/LAST_DIFF.patch   # rollback
```

---

## 28. Стоп-условия (autonomous mode)

```text
task is ambiguous             patch does not apply
files outside allowed scope   too many files in patch
tests fail > N times          diff extraction failed
dangerous command requested   dependency install requested
public API change detected    confidence is low
no test command available     context budget exceeded
```

---

## 29. Definition of Done

```text
patch applied           tests passed
diff is minimal         only allowed files changed
step summary written    STATE.json updated
next step known
```

---

## 30. Session stats

```python
@dataclass
class Session:
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost: float = 0.0
    requests: int = 0
    started_at: datetime = field(default_factory=datetime.now)
```

Обновляется после каждого LLM-вызова. Отображается в статус-баре.
При выходе — записывается в `SESSION.md`.

---

## 31. Роадмап

### ~~v0.1 — proof of concept~~ ✓ закрыта 2026-05-11

Цель: проверить, умеет ли qwen2.5-coder-14b стабильно выдавать применимый patch.

**Ответ:** **15/15 (100%)** после смены формата на SEARCH/REPLACE блоки (по образцу aider, лицензия Apache 2.0). Unified diff давал 12/15 → 13/15 с fuzzy fallback — все оставшиеся отказы упирались в счётчики `@@`, путаницу контекст/изменение и инварианты, на которые слабая модель не вытягивает. SEARCH/REPLACE убирает счётчики и hunk-заголовки целиком: модель пишет «вот что есть» и «вот что должно стать». Подробности: `docs/bench-v0.1.md`, благодарности: `CREDITS.md`.

```text
✓ TUI skeleton + цветовая схема (theme.tcss / styles.tcss)
✓ config loader (pydantic + YAML) + model profiles + автодетект context_tokens
  (LM Studio /api/v0/models → loaded_context_length, fallback на /v1/models)
✓ LLM adapter: chat() + stream() — стрим токенов прокинут в TUI через Markdown.update()
✓ AsyncShellRunner + whitelist
✓ list_files (рекурсивно, исключает .gitignore + все скрытые .*/), read_file
✓ ripgrep search
✓ git diff, status, apply, rollback (apply с --ignore-whitespace)
✓ patch parser (unidiff) + validator + applier + hunk-header normalizer
  (qwen2.5-coder часто врёт со счётчиками строк в @@ — нормализуем)
✓ StepAgent.ask() + stream_ask() — стрим токенов
  System prompt: identity (code-scalpel, не Claude/ChatGPT) +
    разрешает текстовый ответ без diff + отвечает на языке юзера
  Контекст: листинг ВСЕХ файлов (до 200), полное содержимое только первых N
✓ manual step: patch preview + apply (ToolCallCard: running/reviewing/done/error)
✓ run pytest
✓ STATE.json (атомарная запись + step_phase + dirty_patch); дефолт context_limit = 16k
✓ Session stats + context indicator (бар + %)
✓ tests/mocks.py + conftest.py (включая stream())
✓ TUI v0.1 finished:
    • CLI принимает путь-песочницу: `code-scalpel tui /tmp/sandbox`
    • OutputLog = VerticalScroll + spacer → чат растёт снизу вверх
    • Markdown-рендер для ответов модели; margin между сообщениями
    • ModeInput = `> ask` префикс + Input в одну строку, Rule сверху/снизу
    • textual-autocomplete для слэш-команд (/new, /compact, /help, /mode *)
      открывается вверх (_UpwardAutoComplete), описания в дропдауне
    • ESC отменяет активный стриминг-воркер (без падений на CancelledError)
✓ Тесты: stream_ask, autodetect (несколько эндпоинтов/полей),
    list_files без .*, слэш-команды, ESC-отмена, focus, layout
```

> UI язык: English only. i18n — см. v0.4.
> Resume / crash recovery — в v0.2; `dirty_patch` в STATE.json остаётся в v0.1 для безопасности. Реализуется инлайн (notice-карточка в OutputLog при запуске, если STATE.json дёрнут), без отдельного экрана.
> TUI: не начинать с идеальных карточек. Порядок: Input + Footer → ToolCallCard → PlanCard → остальное.

### ~~v0.2~~ ✓ закрыта 2026-05-11

```text
✓ TUI: цвет режима + Ctrl+T (Shift+Tab перехватывался Input для focus_previous)
  • prompt prefix красится цветом mode, mini-hint в footer
  • ask=cyan, plan=gold, step=green, review=coral
✓ Tab focus: VerticalScroll (OutputLog) и CollapsibleTitle ToolUseCard
  выведены из focus-цикла. Cycle = только Input ↔ актуальная
  ToolCallCard (review/apply). История tool-карточек тихая, Ctrl+O —
  единственный путь к last result.
✓ map-as-context + tool-calls-for-reads:
  • static map: AST-символы (path → classes/funcs/constants), кеш в
    .code-scalpel/INDEX.json с mtime-инвалидацией
  • tool-calling loop: read_file / grep (с pure-python fallback на
    rg отсутствие) / run_tests
  • протокол: assistant → tool_call → tool_result → assistant
  • Tool-карточки в TUI (Collapsible одной строкой: name + summary,
    раскрытие по chevron)
  • Эффект: casual «привет» = ~200 токенов вместо 7k
✓ /compact: реальная реализация (summarize history → 1 message)
✓ /new: чистит widgets + state.json + history
✓ stream events типизированы: TextDelta / ToolExecuted
✓ стрим в Static (мгновенный), на finalize → Markdown с подсветкой
✓ tokens/sec в footer
✓ детект языка пользователя (Russian/English) с прибавкой к task'у
✓ ESC прерывает стрим (двойная защита: binding + on_key)
✓ apply_edits атомарный + пустой/whitespace SEARCH = prepend
✓ syntax highlight в diff-карточке через Rich Syntax (lexer=diff)
✓ resume on launch: inline notice-карточка при dirty_patch=True,
  флаг сбрасывается чтобы не нагружать каждый запуск
✓ debug sub-mode: regen-кнопка в diff-карточке re-кормит модели
  предыдущий патч и просит другой подход
✓ session summary при выходе печатается в stdout (typer.echo)
✓ Бенч: 24-test LLM сюита (15 базовых + multi-file + 7 поведенческих +
  1 xfail на grep до native function calling)
✓ Тесты: 150 unit + 23 LLM (8 на историю + tool-loop в моках,
  4 на native function calling в реале)
✓ native function calling: переключение на OpenAI API tools=[...]
  с JSON Schema. Убраны few-shot из системного промта.
✓ Кросс-модельный бенч (см. `docs/bench-models.md`):
  • gemma-4-26b-a4b: 24/24 (100%), 120s — лучшее качество
  • qwen2.5-coder-14b со спек: 23/24 (96%), 45s — лучший Pareto
  • gpt-oss-20b: 21/24 (87.5%), 106s
  • qwen3.5-9b: 19/24 (79%), 73s
  • qwen3.6-35b-a3b: 13/24 (54%), 542s
  • qwen2.5-coder-7b Q6 + спек: 13/24 (54%), 42s
  • qwen3.5-35b-a3b: 10/24 (42%), 303s
  Урок: дефолт остаётся coder-14b, но gemma-4 — реальная
  альтернатива (особенно если поднять спек через assistant-drafter).
```

Перенесено в v0.3:
- ✓ task classifier (local heuristic) — `code_scalpel/classifier.py`, pure
  function, word-boundary regex (чуть строже псевдокода в §21 чтобы
  "prefix" не триггерил "fix"). 29 unit-тестов.
- ✓ per-mode temperature + shared inference params — `ModeTemperatures` в
  `config.py`. Дефолты: ask=0.1 / plan=0.4 / code=0.2 / review=0.1 /
  debug=0.5 (retry diversity). `top_p`/`frequency_penalty`/`seed` — общие
  на все режимы. Float-шорткат (`temperature: 0.2` в YAML) применяется ко
  всем режимам. Бенч переключён на `mode="code"`.
  Заодно переименован UI mode `step` → `code` (понятнее: «модель пишет
  патч», а не «шаг чего-то»). `run` (autonomous) и debug-sub-mode не
  тронуты.
- ✓ informal tone в system prompt — «ты», не «вы»; без «Извините,
  пожалуйста, переформулируйте». Колли́гиальный тон, не корпоративный.
- ✓ grounding rules в system prompt + 4 retrieval-теста в LLM-бенче:
  «map авторитетна, не выдумывай», «cite path:symbol», «read_file перед
  показом кода». Бенч-кейсы: admit-missing-method, reads-file-first,
  не-инвентируй-метод-AgentState (точная репродукция бага 2026-05-11),
  cite-file-when-pointing. Регрессионная защита от галлюцинаций.
- ✓ TUI прозрачность пачкой:
  • model auto-detect через `/v1/models` + ручной override в config.
    Sentinel `"auto"` (плюс legacy `"local-model"`) → автодетект.
  • footer показывает имя модели справа-снизу (dim) — больше не
    «`local-model`» в логах, после resolve подставляется реальный id.
  • `/compact` теперь честно роняет индикатор контекста: `Session`
    держит `compact_baseline_*` снапшот, `context_used_tokens` показывает
    «потрачено с последнего компакта», cumulative totals остаются для
    exit-summary.
  • cursor cell перекрашивается под цвет mode (`mode-ask/plan/code/review`
    CSS-классы).
- planner mode + TASKS.md — большой кусок, рядом с autonomous
- step summarizer — depends on step mode
- context builder compression — пока не упираемся в лимит
- `!cmd` shell escape в инпуте
! <cmd> в инпуте — выполнить bash-команду напрямую (без whitelist, вывод в поток)
```

v0.3 hooks captured in v0.2 (см. ниже):

### v0.3

```text
external SDK survey 2026-05-11 (research-agent report):
  Оценили Letta / OpenHands SDK / mem0 / smolagents / LangGraph
  для замены частей v0.3. Вывод:
  • **mem0 — единственный кандидат на интеграцию** в v0.3 memory layer.
    Композируется как библиотека (pip install mem0ai), narrow API
    add()/search(), local Chroma backend, поддерживает LM Studio через
    OpenAI-compat. Спасает ~30% работы по recall/dedup.
  • **Letta — игнорировать**. Хочет владеть agent loop, требует
    Postgres+pgvector, Docker-first. Lock-in несовместим с нашим
    "small, local, composable" principle.
  • **OpenHands agent-sdk — читать FileEditorTool как референс**, не
    тянуть как зависимость.
  • **AST indexing + symbol graph + summaries — наш moat**, никто не
    делает это хорошо для слабых моделей. Пишем сами.
  Action: spike `mem0ai` на пол-дня когда стартуем memory layer
  именно в v0.3.

project memory + retrieval (BIG, ставит фундамент для всего ниже):
  Сейчас агент видит ТОЛЬКО project map в каждом turn'е. Map хорош но
  плоский: signatures + docstrings + imports. Нужна **многослойная
  память** проекта чтобы агент не зависел от того что юзер помнит
  сказать «прочитай файл X» каждый раз.
  **Update 2026-05-11**: spike-агент прогнал mem0ai 2.0.2 на нашем
  стеке. **Recommendation: SKIP**. Причины:
    1. API instability — mem0 сломал свою же документацию между
       версиями (`search(user_id=...)` → `search(filters={...})`)
    2. LM Studio совместимость требует monkey-patch (mem0 хардкодит
       `response_format={"type": "json_object"}` — LM Studio такое
       не поддерживает, требует `"text"`)
    3. Дедупликация **не работает** в 2.0.2 в vector-пути — главная
       причина брать mem0, а её и нет
    4. +138 MB зависимостей (numpy, grpcio, sqlalchemy, qdrant)
  ✓ Альтернатива реализована: thin `code_scalpel/memory.py` (~166 LOC):
    sqlite + FTS5 (zero new deps), 14 unit-тестов, `MemoryEntry`
    frozen, `MemoryStore.add/search/all/delete/clear/__len__`.
  ✓ TUI wiring: `/remember <fact>` сохраняет, `/recall [query]`
    показывает ToolUseCard. Авто-recall на каждый turn — top-3 OR-
    запрос через FTS5, вставляется в user message как «Recalled
    notes» блок (только если что-то нашлось). Доступ через
    `StepAgent(memory=...)` — DI, как остальное.
  Дальше:
    • Vector-слой (Chroma/Qdrant) — на следующий раз когда FTS5
      перестанет ловить нужное (пока матчит достаточно)
    • Contradiction-check через LLMAdapter
    • phase-3-cleanup: public `StepAgent.attach_memory(memory)` —
      сейчас `ScalpelApp._get_memory()` пишет в `agent._memory`
      напрямую (TUI ↔ агент через приватное поле). Не блокер v0.3
      (один callsite), но в чистом API быть не должно.
  Полный отчёт spike: `/tmp/mem0_spike_report.md`.
  AST/symbols/summaries — наш moat в любом случае.
  Слои:
  • Tree-sitter / AST индекс — granular nodes (functions, classes,
    methods) с позициями, типами параметров, control-flow shape (есть
    ли try/loop/if, количество ветвей). Не только Python — JS, Go,
    Rust. Indexed at session start, invalidated by mtime.
    **Update 2026-05-11**: spike-агент прогнал tree-sitter на нашем
    проекте. Recommendation: **ADOPT, в 2 фазы**. Чистая установка
    (+5.4 MB net useful), perf на Python в шуме vs ast, но ts даёт
    multi-lang (Py/JS/Go/Rust одним walker), error recovery,
    granular byte+line positions, incremental reparsing.
    ✓ Phase 1: новый `code_scalpel/index/` package рядом с
    project_map.py (parser.py / walkers.py / shape.py / model.py +
    tests).
    ✓ Phase 2: shim cutover — `project_map.build_file_map` и
    `find_definitions` теперь зовут `build_file_index`; публичные
    сигнатуры сохранены, все 453 теста зелёные. `build_map` остался
    на ast (cache-keyed full-map путь — больше скоупа), `find_references`
    остался текстовым (никогда не использовал AST).
    Phase 3 (следующая сессия): консьюмеры (agent.py, agent_tools.py,
    tui/app.py) перейдут на index/ API напрямую; `build_map` тоже
    через FileIndex; дедуплицировать `_internal_packages` (он сейчас
    в обоих модулях); удалить ast-only helpers и сам project_map.py
    когда консьюмеров не останется.
    **Trap warning**: `tree-sitter-language-pack` 1.8.0 broken — на
    project_map.py вернул empty docstrings/signatures. Использовать
    индивидуальные пакеты (`tree-sitter-python` etc.).
    Артефакты spike: `/tmp/ts_spike/indexer.py` (~270 LOC).
  • File-scoped summaries — для каждого файла >50 LOC хранить
    сгенерированную моделью одну-две абзаца «что этот файл делает,
    с чем связан». Дешевле чем читать body, точнее чем docstring.
    Регенерация по mtime (как INDEX.json сейчас).
  • Symbol graph — где каждая функция/класс вызывается. Inverse-index
    imports. Pre-computed via AST walk. Дает ответ на «где X
    используется?» без grep.
  • Retrieval API — `retrieve(query, k=5, scope=file|symbol|all)`
    возвращает k наиболее релевантных фрагментов (chunks с BM25 +
    optional embeddings). Используется агентом как ещё одна tool в
    дополнение к read_file/grep.
  Архитектура: `code_scalpel/memory/` директория с `indexer.py`
  (tree-sitter), `summaries.py` (LLM-generated per-file blurbs),
  `graph.py` (call graph), `retrieve.py` (BM25 + tool wrapper).
  Замена иди дополнение к project_map.

✓ navigation-style project map + on-demand drilldown: каждый turn
  модель видит только overview (paths + line counts через
  `build_map_overview`), а сама зовёт `map_file(path)` когда нужны
  сигнатуры/docstrings/imports. Старый «жирный» map ушёл в `/map`
  и initial-turn context. Скейлится на тысячи файлов без раздутого
  бюджета.

✓ goto_definition + find_references (editor-grade navigation, AST-based):
  `goto_definition(name)` отдаёт `path:line  kind  qualified_name` для
  каждого def-сайта; `find_references(name)` — `path:line: code` rows,
  cap 50, whole-word. Парные тулзы поверх AST из project_map, дешевле
  и точнее grep когда символ известен. Регистрируются в TOOL_SCHEMAS,
  диспатч в `tools/agent_tools.execute`. Юнит-тесты разнесены по
  `tests/test_project_map.py` (находилка) и `tests/test_agent_tools.py`
  (схемы + dispatch).

summaries вместо giant context: когда история turn'ов или
  read_file результаты накапливаются — суммировать через LLM в
  компактные note'ы. Уже есть /compact для history; нужно
  расширить на «read_file output после N turn'ов теряет detail,
  превращается в summary». Освобождает контекст для нового.

✓ iterative patch loop (agent-side + TUI wiring): `StepAgent.code_with_retry()`
  применяет patch → run_tests → если красные, кормит pytest output
  обратно модели как retry-context. Cap = `agent.max_debug_attempts`
  (+1 initial attempt). Опт-ин через `agent.iterative_patch_loop`
  (дефолт False). `StepResult.attempts: tuple[PatchAttempt, ...]`
  хранит историю (edits / apply_ok / apply_error / test_output /
  tests_passed). TUI wiring done: `_run_code_with_retry` рендерит
  каждую попытку как inline `patch_attempt_N` ToolUseCard. Если все
  попытки провалились — финальный diff поднимается в ToolCallCard
  для ручного [a]/[r]/[g] (escape hatch сохранён). Слэш-команда
  `/loop` переключает флаг без правки конфига.

mandatory tests: для каждой задачи в plan'е модель должна заявлять
  testы которые покрывают изменение. Если testов нет — задача не
  считается выполненной. Это policy уровня executor: после apply
  проверяем что а) тесты что были — зелёные, б) новые тесты есть
  если задача implement/refactor. Конфликтует с simple `code` mode
  где юзер просит просто patch — нужен toggle.

file-scoped retrieval: вместо «дай k chunks из всего проекта»
  иногда лучше «из этого файла». Полезно когда юзер уже выбрал
  файл (через map или предыдущий turn). API: `retrieve(query,
  path=...)`. Имплементируется поверх tree-sitter индекса.

model bench когда агент допишется (TODO, прямое сравнение на нашей
  v0.3+ сюите, не v0.2):
  • qwen3-8b (новая generation, для проверки поколения)
  • qwen3.5-9b (dense general, уже мерили на v0.2 — 79%, ожидаем
    рост с обогащённой map)
  • qwen2.5-coder-14b (текущий baseline)
  Цель: понять окупается ли coder-специализация vs более новая
  generic-модель + наша обогащённая map. Если qwen3-8b vs coder-14b
  даст близко по качеству при половине RAM — переключаем дефолт.
  Прогоняется на полной сюите (включая retrieval/grounding кейсы,
  которые v0.2 бенч не покрывал).

✓ background jobs registry (UI/UX): closed in two strokes.
  • `code_scalpel/jobs.py` — `JobRegistry` с `start/finish/track`
    контекст-менеджером, subscribe-API (listener получает immutable
    snapshot, broken listeners isolated). 11 unit-тестов на чистой
    логике.
  • `code_scalpel/tui/widgets/jobs_bar.py` — `JobsBar` widget,
    inline над футером, collapse в height=0 при idle, рендер «⚙ N
    jobs: kind1 · kind2 …». Subscribes на mount, unsubscribes на
    unmount. Cross-thread обновления через `call_from_thread`. 5
    pilot-тестов.
  • Wired в ScalpelApp: `/map`, `/compact`, и каждый `_run_step`
    (ask/plan/code/review) трекаются. Plugin-friendly: любая фича
    зовёт `self.jobs.track("kind", "desc")` и она появится в баре.
  Closes UX-pain «непонятно что в фоне крутится».
  Дальше — modal с деталями + cancel (Ctrl+J), когда supervised
  autonomous mode даст одновременные jobs.

✓ identity-блок fix в system prompt: коммит `eb38325` — qwen-coder-14b
  на «кто ты» регулярно ловил мисс-аттрибуцию (отвечал «Ты — ассистент…»
  во втором лице или соскакивал в Claude/GPT-translation). Лечение —
  examples-driven prompting: явные literal triggers («кто ты»,
  «представься», «what are you»…), first-person заготовки ответа на
  ru/en, прямой запрет self-description как fallback. Follow-up
  required: probe показал что блок тянет слишком сильно на короткие
  context-вопросы вроде «где сжимается?», «что тут?» — модель уезжает
  в self-intro вместо ответа из map+tools. Сужать триггеры дальше или
  переезжать на post-hoc guard в агенте.

✓ enforce-read-before-show (HOOK): post-hoc check в
  `StepAgent._chat_loop_with_hook` — если финальный ответ содержит
  SEARCH/REPLACE блок или fenced python для файла из таска, и
  `read_file` для этого пути ни в текущем, ни в прошлых ходах не
  звался, отклоняем и шлём модели re-prompt («прочитай сначала, потом
  перепиши»). Cap = 1 retry (упрямую модель в цикл не загоняем).
  Tracked across turns в `self._read_files_history`, сбрасывается в
  `clear_history`/`compact`. Opt-out: `agent.enforce_read_before_show`.
  Под qwen-coder-14b bench `test_qwen_reads_file_even_for_vague_show_code`
  стабильно зелёный. `remove_unused_import` остался xfail — там модель
  фабрикует prose-ответ «no imports here» без кодового блока, что вне
  scope HOOKа (нечего детектить как ungrounded emission).
diagram-shape guidance (HOOK, наблюдение 2026-05-11):
  Юзер прошёлся по реальному сценарию «найди алгоритм сжатия
  контекста». На запросе «составь диаграмму» модель нарисовала
  пятиэкранный ASCII-арт всех файлов проекта (file tree), а на
  уточнении «диаграмму того как работает» — крошечную структурную
  схему `session.py / memory.py → mark_compacted → context_used_tokens`,
  ошибочно включив `memory.py` (он про /remember, не про сжатие)
  и пропустив главный код пути — `StepAgent.compact()` и
  `_do_compact()` в tui/app.py. Алгоритм описан только своим хвостом
  (anchor baseline), сама LLM-суммаризация истории не упомянута.
  Что делать:
    ✓ Рендер сделан (2026-05-11): `code_scalpel/diagrams.py` +
      `tui/widgets/mermaid_card.py`. Детектим ```mermaid``` fenced-блоки
      в финальном ответе, монтируем `MermaidCard` в OutputLog до
      apply-card. Tier-1 (mmdc on PATH + rich-pixels) → PNG → Unicode
      half-blocks inline. Tier-2 (mmdc упал) → текст + строка ошибки.
      Tier-3 (deps нет) → raw source + install hint. `rich-pixels` —
      optional dep (`pip install -e .[diagrams]`), Node CLI ставится
      руками юзером.
    • TODO: prompt-half. В system prompt отдельный блок про диаграммы:
      distinguish flow vs structure. «Как работает X» — это
      sequence/flow, не file tree. Steer модель к Mermaid (рендер
      теперь есть — ASCII art смысла больше не имеет).
    • Перед утверждением «X использует Y» вызови map_file(X) и
      проверь `imports:` (current grounding rule, but модель его
      игнорирует в свободном тексте — нужно подсилить или вынести
      в post-hoc check как enforce-read-before-show).

follow-up search (HOOK, тот же сценарий):
  На T3 «именно алгоритм сжатия» модель повторила материал из T1
  (session.py), не grep'нула `compact` и не goto_definition'ом
  для `compact` на StepAgent. Когда юзер уточняет тему, модель
  относится к новому turn'у как к follow-up к прежнему answer'у,
  не как к расширению поиска. Возможные пути:
    • Prompt rule: «при уточнении/расширении темы — повтори
      tools, не доверяй кэшу контекста; новый угол → новый поиск».
    • Detection в агенте: если turn N-1 завершился ответом, а
      turn N начинается с «именно/конкретно/точнее/имел ввиду»,
      инжектить hint «expand search before answering».

context indicator semantics (HOOK): сейчас footer показывает
  «накоплено с последнего /compact» через compact_baseline. Это лучше
  кумулятива, но не идеал — настоящее «сколько весит следующий промт»
  должно считаться как system + history + map. Когда появится
  context/builder.py, переехать туда и убрать baseline-хак из Session.
gemma+спек retry (TODO с следующей сессии): сейчас заблокировано
  OOM на 16 GB VRAM (gemma-4 26B Q4 = 18 GB > 16 GB - desktop). Два
  пути: (1) дискретная display-карта чтобы освободить 5060 Ti
  полностью; (2) собрать CUDA-build llama.cpp (vs текущий Vulkan
  которому не хватает memory-allocator efficiency). Цель: 24/24 +
  ~60s со спек = новый абсолютный чемпион. См. подробности в
  `docs/bench-models.md`.
✓ tool-result viewer (был HOOK): Ctrl+O попап с подсветкой
  синтаксиса, line numbers, real xclip/wl-copy/pbcopy clipboard,
  async render placeholder. Custom project_map highlighter без
  Pygments. `tool_result_modal.py` + `_map_highlight.py`.
✓ HistoryInput (bash-style ↑/↓ в инпуте, коммит `f008c7a`):
  `code_scalpel/tui/widgets/input.py:HistoryInput` — priority-bindings
  на ↑/↓ перехватывают раньше textual-autocomplete (раньше ↓ открывало
  дропдаун слэш-команд, что для шелл-инпута неправильный default).
  HISTCONTROL=ignoredups, draft-stash при walk-past-newest, per-widget
  in-memory (cross-session — позже).
✓ Ctrl+↑/↓ навигация по tool-карточкам (коммит `d5a4a8b`):
  ScalpelApp BINDINGS `ctrl+up`/`ctrl+down` прыгают между inline
  ToolUseCard в OutputLog, Esc возвращает фокус в инпут. Закрывает
  UX-pain «как добраться до карточки сверху без мыши».
✓ inline streaming/thinking widget (был на v0.3): `TurnProgress`
  виджет монтируется в чате, обновляется по тикам стрима, удаляется
  при финализации. Футер ушёл от streaming-индикаторов полностью.
✓ /stats slash (заменил /system, коммит `439608f`):
  `Session.stats_report` — токены / стоимость / тайминги — печатает
  inline как свёрнутую ToolUseCard (`session_stats`). Старый /system
  выдавал system prompt, что сейчас в чате не нужно (он стабильный,
  не меняется per-turn); /stats закрывает реальную нужду «куда улетел
  контекст и сколько это стоило».
✓ planner mode + TASKS.md (первая половина): plan-mode addendum в
  промте, агент пишет .code-scalpel/TASKS.md. Run-mode execution
  loop — в следующих коммитах.
✓ supervised autonomous mode (run-plan loop): `StepAgent.run_plan`
  walks `.code-scalpel/TASKS.md`, executes каждую `## T###:` через
  существующий `code_with_retry`, ставит `[✓]` атомарно (.tmp →
  rename). TUI slash `/run` дёргает loop через JobsBar, рендерит
  per-task status + per-task `T00N_attempt_*` cards + финальный
  inline summary. Esc отменяет worker.
✓ stop conditions enforcement: реализован минимально-достаточный
  набор для run-plan — N подряд failures (default 2 → reason
  `max_failures`), `asyncio.CancelledError` (Esc → reason
  `cancelled`, уже отмеченные [✓] остаются на диске), хэш TASKS.md
  изменился между итерациями (reason `plan_modified` — защита от
  гонки с редактором), все задачи done (reason `all_done`),
  отсутствие/пустота файла (reason `no_tasks`). Остальные пункты
  раздела 28 (`dangerous command`, `public API change`, `confidence
  low` и пр.) — отдельный кусок, не блокер для базового run.
SkillRegistry (MD + Python)
PythonSkill built-in
DockerSkill (component skill демо)
learn command (из знаний модели)
session summary при выходе
dual-model setup — ОТЛОЖЕНО ДО ПОСЛЕ v0.4 (см. ниже).
  Кросс-модельный замер показал что:
    • coder-14b — лучший Pareto-выбор (96% качества, 45s)
    • gemma-4-26b-a4b — лучшее качество (100%, но 120s)
    • gpt-oss-20b — кандидат для plan/review (общее рассуждение)
  Архитектура (когда будем делать) — ТРИ ВАРИАНТА dual-mode:
    (A) **API подписка для умного профиля**: coder локально +
        Claude/GPT через API для plan/review. Минус — compliance
        сегмент не может, нужно либо отказаться от него либо
        делать опт-ин.
    (B) **Co-resident локально**: gemma+coder одновременно в VRAM
        (если влезает). Быстрая эскалация, нулевая задержка
        swap'а. Минус — мало у кого 30+ GB VRAM.
    (C) **Sequential local model swap**: planner-фазы грузят
        тяжёлую модель (gemma-4-26b / gpt-oss-20b / qwen3.5-72b),
        она думает 5–20 минут над планом/ревью, потом
        выгружается, грузится coder-14b и кодит по плану.
        LM Studio /v1/models позволяет programmatic-swap; это
        работает и на 16 GB VRAM. Архитектурно — `model_phases`
        в config: `{plan: heavy, code: fast, review: heavy}`.
        Минус — общая latency растёт; компенсируется тем что
        думающие фазы происходят редко и асинхронно (юзер
        формулирует план один раз, потом 20 minutes can wait).
    Развилка между всеми режимами — конфиг, не код. Один и тот же
    StepAgent должен уметь работать в любой конфигурации.
  СТРУКТУРА КОНФИГА (явное требование 2026-05-11):
    Профиль = набор моделей под agent-режимы. Формат: dotted-key
    overrides. Базовый `llm` спека наследуется во все режимы; любой
    `llm.<mode>` точечно переопределяет. Спека модели —
    single-string `provider:model[?opt=val&opt=val]`. Параметры
    через query-string чтобы остаться на одной строке.

    Пример YAML — все четыре варианта в одном файле:

      profiles:
        local-fast:                       # всё локально, всё быстро
          llm: 'lmstudio:qwen2.5-coder-14b'

        local-heavy-plan:                 # вариант (C): swap для plan
          llm: 'lmstudio:qwen2.5-coder-14b'
          llm.plan:   'lmstudio:gemma-4-26b-a4b?swap'
          llm.review: 'lmstudio:gemma-4-26b-a4b?swap'

        api-mix:                          # вариант (A): coder лок + API ум
          llm: 'lmstudio:qwen2.5-coder-14b'
          llm.plan:   'anthropic:claude-sonnet-4-5'
          llm.review: 'anthropic:claude-sonnet-4-5'

        co-resident:                      # вариант (B): две в VRAM
          llm: 'lmstudio:qwen2.5-coder-14b'
          llm.plan:   'lmstudio:gemma-4-26b-a4b'
          llm.review: 'lmstudio:gemma-4-26b-a4b'

        mixed-experiment:                 # тонкий контроль по каждому
          llm: 'lmstudio:qwen2.5-coder-14b?temperature=0.2'
          llm.ask:    'lmstudio:qwen3.5-9b?temperature=0.1'
          llm.plan:   'anthropic:claude-opus-4-7?temperature=0.4'
          llm.code:   'lmstudio:qwen2.5-coder-14b?temperature=0.2'
          llm.review: 'lmstudio:gemma-4-26b-a4b?swap&temperature=0.1'

      active_profile: local-fast          # /profile slash в TUI переключает

    Семантика shorthand:
      `provider:model` — обязательная часть, разделитель `:`
      `?key=val&key=val` — query-string опции. Без `=` (как `?swap`) —
        флаг true. Известные опции: `swap` (model_swap для local
        sequential), `temperature`, `timeout`, `max_tokens`, `seed`,
        `top_p`. Неизвестные опции игнорируются с предупреждением,
        не падают.
      Provider'ы — plugin-friendly registry. Встроенные нами планируются:
        `lmstudio`, `llamacpp`, `ollama`, `vllm` (local) + `openai`,
        `anthropic` (cloud). Каждый знает свой base_url, auth-flow
        и фичи (function calling / streaming / model-swap API).
      Третий сторонний provider — пишется один Provider-класс с
        интерфейсом `chat()`/`stream()`/`list_models()` и
        регистрируется через entry-point (или просто
        `register_provider(name, class)` в `code_scalpel.config`).
        В YAML появляется новый префикс — `myorg-internal:llama-70b`
        — и всё, никаких других изменений в проекте не требуется.
        Это та же plugin-точка что и Skills и Memory backends:
        ядро не должно знать про конкретный провайдер.

    Код:
      • `ModelSpec.parse(spec_string) -> ModelSpec` — парсер
        provider:model?opts (~30 LOC, тестируется отдельно).
      • `ModelProfile` хранит `llm: ModelSpec` и `mode_overrides:
        dict[str, ModelSpec]`. Метод `spec_for(mode)` отдаёт
        правильную с fallback на базовую.
      • Pydantic root_validator собирает `llm.<mode>` ключи в
        `mode_overrides` при загрузке YAML (dotted-keys в YAML —
        обычные string-ключи, не nested).
      • `LLMAdapter.for_spec(spec)` — фабрика; кэшит клиенты по
        (provider, model), переиспользует между режимами.
      • Когда `?swap` стоит — оркестратор перед запросом дёргает
        LM Studio /v1/models/load с нужным id, после завершения
        возвращает coder. Swap прозрачен для агента.

    Точка композиции — конфиг. Единственная. Никаких if'ов «if
    dual_model:» в коде агента.
  ПРИНЦИП (явное product-решение, 2026-05-11):
    Дальняя цель — подпереть локального 14b более умной моделью
    для plan/review/architectural reasoning. Предпочтительный
    путь — вариант (C) local sequential swap, потому что
    сохраняет «полностью локально» позицию и не требует
    подписки. Вариант (A) — опт-ин для тех у кого есть API
    бюджет; вариант (B) — для счастливчиков с большим VRAM.
    Но это NOT NOW. Сначала исчерпываем single-model локальный
    путь: разбираемся с кодингом, supervised autonomous loop,
    summaries, tree-sitter Phase 2. И только после того как
    практика покажет конкретные неперебарываемые ограничения
    (задокументированные в article + probe-результатах, а не
    «кажется не тянет»), переходим к dual-model.
    Иначе сравнение с Claude/большими моделями убивает мотивацию
    делать одиночный локальный путь хорошо. Целевая позиция —
    «локальный jr.dev для compliance-сегмента». Dual-model
    (особенно (A)) — добавка для тех кто может, не дефолт.
self-clarify loop (HOOK, экспериментально): когда модель в ходе задачи
  задаёт уточняющий вопрос пользователю — попробовать перехватить и
  скормить тот же вопрос ей же с другим контекстом. Два варианта:
    • чистый контекст: модель отвечает «из общих знаний», без шума
      проекта — подходит для общих архитектурных вопросов
    • расширенный контекст: подкидываем больше файлов / релевантных
      кусков — подходит для конкретики
  Ответ транслируем назад в основной цикл агента вместо ожидания
  пользователя. Полезно для полного авторежима, но риск «эхо-камеры»
  — модель отвечает себе сама и идёт по неверной траектории. Нужны
  hard-stop'ы: лимит self-clarify раундов на задачу, явный fallback к
  пользователю на сомнительных ответах.
```

### v0.4

```text
learn --url (httpx fetch + skill генерация) — риск: HTML-мусор, устаревшие доки, большие страницы; нужен бюджет на чистку
JS / Go / Rust language skills
PostgreSQL / Kubernetes component skills
LLM-based context compression (для strong профилей)
configurable policies
i18n: ru/en, автодетект по системной локали
```

---

## 32. Главный пользовательский сценарий

```bash
cd my-project && code-scalpel init && code-scalpel
```

Режим: `plan`. Вводит: "Добавь поиск заметок".  
Агент: план T001–T004. Пользователь переключается в `run`.

```text
T001 ✓  T002 ✓  T003 ✗ → debug → ✓  T004 ✓
pytest: 5 passed
Session: 12 241 in / 2 103 out  $0.00  [local]
```

---

## 33. Локализация (i18n) *(v0.4)*

**v0.1–v0.3: English only.** Промты на английском — лучше работает с локальными моделями.
UI-строки тоже английские; переводить нечего до появления реального запроса.

**v0.4 (если понадобится):** `t()` + `ru.yaml` / `en.yaml`, автодетект по системной локали.
Что переводить: статус-бар, лейблы, ошибки. Что не трогать: команды CLI, имена файлов, hotkeys.

В конфиге зарезервировано: `language: en  # en | ru (v0.4)`

---

## 34. Возобновление сессии

Состояние хранится в `.code-scalpel/` внутри проекта — привязка к конкретному проекту.

### Источники правды

```text
git status     → есть ли незакоммиченные изменения (код)
STATE.json     → на каком шаге были (прогресс)
TASKS.md       → что сделано, что осталось (план)
LAST_DIFF.patch → последний патч (для review при resume)
```

### Resume flow при запуске

Если `STATE.json` содержит незавершённую задачу:

```text
┌─ Resume? ──────────────────────────────────┐
│ Task: T002  Phase: testing                 │
│ Git: 2 modified files                      │
│                                            │
│ [R] Continue   [N] Start over              │
└────────────────────────────────────────────┘
```

### Восстановление по `step_phase`

```text
generating  → начать шаг заново (LLM stateless)
reviewing   → показать LAST_DIFF.patch, предложить apply/reject
applying    → git status dirty → предложить rollback или продолжить
testing     → перезапустить тесты (патч уже применён)
idle        → продолжить с current_task
```

### Crash recovery

```text
при старте:
  1. git status → есть uncommitted changes?
  2. STATE.json → dirty_patch: true?
  3. оба да → "Найден незавершённый патч. Применить / Откатить?"
  4. только git dirty → "Есть изменения вне агента. Продолжить?"
```

---

## 35. Суть продукта

```text
code-scalpel is a disciplined patch assistant.

It does not try to understand the whole project at once.
It cuts only where needed.
```

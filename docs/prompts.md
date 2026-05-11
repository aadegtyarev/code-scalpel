# Как писать промты и описания тулз для слабых LLM

Документ собран по результатам итерации **2026-05-11**, когда qwen-coder-14b
галлюцинировал `AgentState.summary_line()` (метод которого нет в проекте) и
конфабулировал тела методов. Сценарий ломался по разным причинам в каждой
итерации; уроки ниже — то что выжило.

## Контекст

Цель проекта — **harness вокруг слабой локальной модели** (qwen-coder-14b,
gemma-4-26b и т.п.). Слабые модели НЕ умеют сами решать «нужно ли мне
сейчас читать файл». Они следуют сигналам в:

1. Описание тулз (передаётся в `tools=[...]` API через JSON Schema).
2. Системный промт.
3. Project map в user-сообщении.

**Когда какой-то из этих трёх источников шепчет одно а другой — другое,
модель ломается.** Это и есть основной сорт багов в харнесе.

## Урок 1: описание тулзы — это **контракт**

Тулза описывается в JSON Schema. Модель прочитает это описание дословно
и будет следовать ему буквально.

**Антипаттерн** (из коммита, которой мы потом откатывали):

```
"description": "Read a project file in full. Returns the file content
with line numbers. Use before producing SEARCH/REPLACE blocks for that file."
```

Это сигнал «я для edit-режима». В ask-режиме («покажи код») модель
сравнивает с этим описанием → «не мой случай» → не вызывает тулзу →
паттерн-матчит тело из обучения. Галлюцинации.

**Паттерн**: описание ДОЛЖНО перечислить **все легитимные случаи**
вызова. Концентрированно, без размытия:

```
"You MUST call this in any of these cases:
(1) Before producing a SEARCH/REPLACE block for that file — your SEARCH
    text has to match the file character-for-character including the
    body, and the MAP doesn't show bodies. Using a MAP signature as
    SEARCH text will fail.
(2) The user asks you to SHOW, QUOTE, or DISPLAY a function body...
(3) You're about to claim a fact about what a method does..."
```

Каждый случай — конкретный, с anti-pattern явно («Using a MAP signature
as SEARCH text will fail»).

## Урок 2: промт **не должен дублировать** контракт тулзы

Сначала мы написали правила «когда звать read_file» и в описании тулзы,
и в системном промте. Они слегка расходились в формулировках. Модель
получала противоречие → выбирала какое-то одно → ломалась на сценариях
которые покрывало второе.

**Паттерн**: системный промт **отсылает** к описанию тулз:

```
You have tools: read_file, grep, run_tests. Each tool's own description
tells you when to call it — READ THOSE DESCRIPTIONS, they are normative.
```

Системный промт оставляет за собой **только то что нельзя выразить в
описании тулзы** — общие правила (тон, идентичность, формат
SEARCH/REPLACE, anti-confabulation rules).

## Урок 3: anti-confabulation rules — конкретные anti-examples

Абстрактное «не выдумывай» не работает. Модель не знает что считается
выдумкой.

**Антипаттерн**: «Never invent function/method names.»

**Паттерн**: дать **конкретный концептуальный пример** того что
запрещено:

```
A similar-looking method name in the MAP does NOT justify inventing
the one the user implied. Example: if the MAP shows `mark_compacted`
on a class, do not answer with `compact` — those are different names.
```

И отдельно — anti-pattern по паттерн-матчингу:

```
Pattern recognition is NOT a source of truth. If a class looks like
a dataclass / BaseModel / typical CRUD shape, you might "know" the
body — you do not. Call read_file every single time you reproduce
more than a signature.
```

## Урок 4: примеры в промте — модель копирует их дословно

Когда мы написали «say "В state.py есть AgentState, но метода
summary_line там нет"» как иллюстрацию правильного ответа, модель
буквально процитировала эту фразу как ответ — даже когда речь шла о
другом классе в другом файле. Классический prompt-leak.

**Антипаттерн**: литеральные strings («Извините, переформулируйте» — не
говори; «say X» — скажи).

**Паттерн**: описывать **форму** ответа, не давать готовые строки:

```
Say "there is no such method, the class only has X, Y, Z" (with the
REAL names from the MAP).
```

«REAL names from the MAP» — указание на **источник**, не на конкретную
строку. Модель подставляет имена из текущего контекста.

## Урок 5: tool template примеры тоже копируются

В формате SEARCH/REPLACE мы писали пример с placeholder-путём:

```
    path/from/the/map.py
    ```python
    <<<<<<< SEARCH
```

Модель буквально приставляла `path/` к именам файлов — `path/greet.py`
вместо `greet.py`. apply_edits валился.

**Паттерн**: использовать в шаблонах **правдоподобное конкретное имя**,
не placeholder-строку:

```
    helpers.py     # не "path/from/the/map.py"
    ```python
    <<<<<<< SEARCH
```

Плюс явный запрет в SEARCH/REPLACE rules:

```
- The first line of the block is the file name EXACTLY as it appears
  in the MAP — do not add a "path/" prefix, do not invent directories.
```

## Урок 6: tone — заменители, не запреты

Запрет «не используй формальный тон» — пустой сигнал, модель не знает
на что заменить.

**Паттерн**: для каждого запрета — конкретная альтернатива:

```
In Russian: ALWAYS use "ты", NEVER "вы". No "Извините", "Пожалуйста,
переформулируйте", "Я не могу" — instead "Не понял, переспроси?",
"Уточни что именно", "Не получается, давай иначе".
```

Это набор замен. Модель видит запрещённую конструкцию рядом с
разрешённой и применяет mapping.

## Урок 7: проверять обе ветки (ask и edit) после любого изменения промта

Когда мы переписали read_file под ask-режим, ОТЛЕТЕЛИ 6 code-gen
тестов: модель стала использовать map-signatures как SEARCH text.

Промт оптимизируется в одну сторону → ломается в другую. **Бенч должен
покрывать обе**:

- ask: «admits_missing_method», «reads_file_before_showing_code»,
  «does_not_invent_class_method», «cites_file_when_pointing».
- edit: 15 кейсов `test_qwen_produces_applicable_patch` (add_type_hints,
  rename, extract_helper, etc.).
- continuity: history между turns, tool round-trips.

**Перед коммитом промт-изменения** прогнать ВЕСЬ бенч:

```bash
pytest --run-llm -m llm tests/test_llm_bench.py -v
```

## Урок 8: temperature и mode — отдельные ручки

Глобально низкая temperature (`0.1`) убивает code-gen — модель
становится дубовой. Глобально высокая (`0.8`, дефолт LM Studio) — ask
конфабулирует.

**Паттерн**: per-mode temperature через `ModeTemperatures`:

```yaml
temperature:
  ask: 0.1      # retrieval, никакой креативности
  plan: 0.4     # планирование может быть шире
  code: 0.2     # код — низко-средне
  review: 0.1   # анализ
  debug: 0.5    # retry нужен diversity иначе тот же патч
```

И передавать `mode` в `agent.ask(task, mode=...)` явно из TUI/CLI.

## Урок 9: spy перед тем как чинить

Когда модель «не делает X», сначала **посмотри что модель видит**:

```python
class SpyAdapter:
    async def chat(self, messages, *, tools=None, **kw):
        self.last_messages = messages
        self.last_tools = tools
        return await real.chat(messages, tools=tools, **kw)
```

Дампи весь payload — system prompt + map + history + tool schemas — и
читай **как читала бы модель**. Половина наших итераций «починили промт»
была впустую потому что мы не видели реальной картины. После одного
spy-прогона стало очевидно что описание read_file противоречит правилу
в промте.

## Чеклист перед коммитом промт-изменений

- [ ] Spy-дамп показывает что модель видит ровно то что ожидаешь.
- [ ] Описание каждой тулзы покрывает ВСЕ её use cases (не только edit).
- [ ] Системный промт не дублирует то что в описании тулзы.
- [ ] Anti-confabulation rules дают конкретные anti-examples (имена,
      паттерны типа dataclass).
- [ ] В промте нет литеральных strings которые модель может
      процитировать как ответ.
- [ ] Tone-правила дают замену для каждого запрета.
- [ ] Templates используют реалистичные имена, не placeholder-строки.
- [ ] LLM-бенч прогнан целиком (ask + edit + continuity); 28+/30 passing.
- [ ] Unit-тест на структуру промта проверяет ключевые анкеры (есть
      grounding, есть mark_compacted vs compact пример, есть dataclass-rule).

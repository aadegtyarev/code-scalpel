# Кросс-модельный замер (v0.2)

## Методология

**Бенч-сюита:** 24 теста, расположены в `tests/test_llm_bench.py`:
- 15 базовых правок (`test_qwen_produces_applicable_patch`):
  type hints, rename, fix off-by-one, replace .format → f-string,
  wrap try/except, extract helper, и т.д. На каждой задаче
  создаётся временный git-репо с маленьким файлом, агенту даётся
  prompt, ответ применяется через `apply_edits`, проверяется
  результирующий код.
- 1 multi-file navigation (агент должен через map выбрать нужный
  файл из 3 и прочитать через read_file).
- 7 поведенческих: история между turn'ами (2 и 3 turn), identity
  (не выдаёт себя за Claude/GPT), plain-text без diff'а на не-
  кодовый вопрос, ответ на русском когда спросили по-русски,
  создание нового файла через пустой SEARCH, эмиссия структурных
  tool_calls вместо текста, история после tool-call round-trip.
- 1 xfail на grep (модель не зовёт grep явно — ждёт v0.3 native
  function expansion).

**Архитектура:** одна и та же на всех моделях — project map (AST-
based), native OpenAI function calling, SEARCH/REPLACE applier с
whitespace-tolerance cascade. Никаких per-model хаков. Отличается
**только** модель (`_PROFILE.model` в bench-файле).

**Прогон:** `pytest --run-llm -m llm` против LM Studio на
localhost:1234. `temperature=0.1`, `seed=42`. Каждая модель
прогонялась один раз (мы видели ранее на v0.1 что цифры
детерминированно повторяются между прогонами на той же модели).

**Железо:**
- GPU: NVIDIA RTX 5060 Ti, 16 GB VRAM, driver 595.58.03
- CPU: Intel Xeon E5-2678 v3 (2.5 GHz)
- RAM: 32 GB
- OS: Ubuntu 24.04 LTS
- Backend: LM Studio (llama.cpp под капотом), `loaded_context_length=16384`

## Таблица

| модель | размер | arch (tokenizer) | quant | спек | pass | время | tok/s clean |
|---|---|---|---|---|---|---|---|
| **google/gemma-4-26b-a4b** | 26B MoE (4B active) | gemma4 | Q4_K_M | выкл | **24/24 (100%)** | ~120s | 30.8 |
| qwen2.5-coder-14b | 14B dense | qwen2 | Q4_K_M | вкл (draft qwen2-0.5B Q6) | 23/24 (96%) | **~45s** | ~80 |
| openai/gpt-oss-20b | 20B dense | gpt-oss | MXFP4 | выкл | 21/24 (87.5%) | ~106s | — |
| qwen3.5-9b | 9B dense | qwen35 | Q4_K_M | выкл | 19/24 (79%) | ~73s | 52.5 |
| qwen3.6-35b-a3b | 35B MoE (3B active) | qwen35moe | Q4_K_M | выкл | 13/24 (54%) | ~542s | — |
| qwen2.5-coder-7b | 7B dense | qwen2 | Q6_K | вкл (draft qwen2-0.5B Q6) | 13/24 (54%) | ~42s | — |
| qwen3.5-35b-a3b | 35B MoE (3B active) | qwen35moe | Q4_K_M | выкл | 10/24 (42%) | ~303s | 21.4 |
| meta-llama-3.1-8b | 8B dense | llama | Q4_K_M | выкл | 9/24 (37.5%) | ~415s | 63.7 |

(`arch` и `quant` берутся из LM Studio's `/api/v0/models` — это
tokenizer-семейство и тип квантизации соответственно. `MXFP4` —
microscaling 4-bit формат от OpenAI, GPU-friendly.)

`tok/s clean` = chunks-per-second в стриме после первого токена, на фикс-промте
«Write a Python function that returns the first n primes».

## Чарт отказов

| тест | gemma-4-a4b | coder-14b | gpt-oss-20b | qwen3.5-9b | qwen3.5-a3b | qwen3.6-a3b |
|---|---|---|---|---|---|---|
| add_type_hints | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ |
| rename_function | ✓ | ✓ | ✗ | ✓ | ✗ | ✓ |
| add_default_parameter | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| add_docstring | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ |
| fix_off_by_one | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| add_empty_input_guard | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| replace_format_with_fstring | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| add_missing_import | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| wrap_in_try_except | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| remove_unused_import | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| add_class_method | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| change_return_type | ✓ | ✗ | ✓ | ✓ | ✗ | ✓ |
| convert_list_to_set | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| add_argument_validation | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| extract_helper | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| multi-file navigation | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| history-2-turn | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| history-3-turn topic | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| plain text | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| identity | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| русский язык | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| new file via empty SEARCH | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| native tool emission | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| history after tool call | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

## Выводы

**По качеству:** coder-14b > gpt-oss-20b > qwen3.5-9b > qwen3.6-35b-a3b > qwen3.5-35b-a3b

**По скорости (то же железо):**
| модель | время | относит. coder-14b |
|---|---|---|
| coder-14b (со спек) | 45s | ×1 (эталон) |
| qwen3.5-9b (без спек) | 73s | ×1.6 |
| gpt-oss-20b (без спек) | 106s | ×2.4 |
| qwen3.5-35b-a3b (без спек) | 303s | ×6.7 |
| qwen3.6-35b-a3b (без спек) | 542s | ×12 |

**Distribution > size:**
- 14B coder-специализированная (96%) обходит 20B general (87.5%)
- 9B general dense (79%) обходит 35B general MoE (42-54%)
- Параметры не главное — главное что модель видела в тренировке + dense ли это

**Pareto-фронт на нашей задаче:**
- coder-14b — лучшее качество и скорость
- qwen3.5-9b — лучше всех general'ов как баланс (быстрая + 79%)
- gpt-oss-20b — медленнее 9B и качества столько же. Не Pareto-оптимален
- 35B-MoE — не работают для нашей задачи в LM Studio

**MoE в LM Studio:** qwen3.5-35b-a3b даёт 21 tok/s — медленнее ожиданий
для модели с 3B активных параметров. LM Studio не оптимизирован для MoE
как vLLM/SGLang.

**Антисюрприз — qwen2.5-coder-7b Q6 + спек:** 13/24 (54%), ~42s.
Хуже coder-14B-Q4 (96%) при почти той же скорости (45s). Это **не
чистое сравнение** — квантизация разная (Q6_K vs Q4_K_M), но точка
интересная как есть:

- 7B Q6 (~6.3GB) почти не быстрее 14B Q4 (~9GB) — target и так
  достаточно маленький, спек добавляет verify-оверхеда столько же
  сколько экономит generation, выигрыш близок к нулю.
- Качество просело сильно — на 42 пункта. Q6 vs Q4 разница в шуме
  (~1-3% на стандартных бенчах), значит остальные 39+ пунктов — за
  счёт **меньшего числа параметров**.

Что **не** проверили (и не можем без новых скачиваний):
- 7B Q4_K_M (одинаковая квантизация с 14B) — был бы чистый
  параметрический тест
- 7B Q8_0 (~8GB, такой же бюджет памяти как 14B Q4) — был бы
  тест «лучшая квантизация при том же footprint'е»

Но даже из имеющейся точки видно: **в диапазоне 7B↔14B параметры
доминируют над выбором квантизации в этой связке**.

**Сюрприз — gemma-4-26b-a4b:** общая MoE-модель от Google взяла
**24/24 (100%)** и обогнала всех включая coder-14b. Тот единственный
`change_return_type` который coder-14b стабильно валил — gemma тоже
прошла. При этом:
- Это general (не coder-tuned) модель → опровергает «coder-tuning
  обязателен для patch-tasks»
- Это MoE (4B active) → опровергает «MoE на LM Studio неюзабельны»
- Скорость 30.8 tok/s — медленнее coder-14b со спек (~80), но всё
  ещё практична (120s бенч против 45s)

Возможные причины почему именно gemma-4 в отличие от qwen3.5-a3b:
1. **Лучшая MoE-маршрутизация** — Google пушила MoE-исследования
   давно (GShard, Switch Transformer), их routing может быть
   стабильнее
2. **Активных параметров 4B vs 3B** — на 33% больше пути, меньше
   несогласованности между токенами
3. **arch=gemma4** — другой tokenizer, другая разбивка кода. Может
   быть код-strings разбиваются на токены так что копирование
   сохраняет байты лучше
4. **Тренировка**: gemma 4 могла видеть много diff/git материала
   несмотря на «general» лейбл

Какая комбинация решающая — нам без файнтюна не узнать. Факт:
**на нашем бенче gemma-4-26b-a4b — №1 по качеству, №3 по скорости**.

## Попытка gemma+спек через llama.cpp напрямую (отложено)

LM Studio блокирует pairing (см. ниже), но llama.cpp в принципе
поддерживает gemma-4 + assistant-drafter. Попробовали поднять
`llama-server` своими руками — упёрлись в **OOM на 16 GB VRAM**:

- llama.cpp pre-built бинари в свежих релизах только Vulkan / ROCm /
  SYCL / OpenVINO / CPU. CUDA-build надо собирать самим
  (`nvidia-cuda-toolkit` + 10 мин компиляции).
- Vulkan-allocator менее компактный чем CUDA — на 18 GB модели Q4_K_M
  + draft 0.3 GB + KV 8k не хватает места. Постоянная OOM ошибка на
  выделении ~870 MB tensor-buffer'а в самом конце загрузки.
- LM Studio AppImage внутри содержит CUDA-сборку llama.cpp как
  `.so` библиотеки + node-binding, но без standalone `llama-server`.
  Извлечь обёртку не получилось без раскопок electron-обёртки.

**Решение (отложено в TODO):** добавить дискретную display-карту
(GT 1030 / GTX 1050 за ~$50-100 б/у). Сейчас 1.3 GB на 5060 Ti
занимает desktop compositor; с отдельной display-картой будут
все 16 GB на LLM, gemma+спек влезет с запасом через Vulkan.
Альтернативно собрать CUDA-build llama.cpp.

## MoE + спек на LM Studio: пробовали, не вышло

Мы попытались включить спек для gemma-4-26b-a4b с её official
purpose-built drafter'ом от Google
(`AtomicChat/gemma-4-26B-A4B-it-assistant-GGUF`, 0.4B, тот же 262K
vocab). LM Studio **отказался их пэйрить** — у assistant-варианта
arch=`gemma4_assistant`, у target arch=`gemma4`. Текст в UI:
*«Не найдено ни одной совместимой черновой модели для вашего
текущего выбора модели»*.

Это [LM Studio bug #1597](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/1597)
— открыт 2026-03-02, висит без owner'а. Та же проблема блокирует
Qwen3.5/3.6 dense → A3B target pairing.

**Альтернативы (вне scope нашего v0.2 замера):**
- SGLang с EAGLE3 head для A3B family. Готовый head для
  qwen3-coder-30b-a3b есть в
  [lmsys/SGLang-EAGLE3-Qwen3-Coder-30B-A3B](https://huggingface.co/lmsys/SGLang-EAGLE3-Qwen3-Coder-30B-A3B-Instruct-SpecForge).
- vLLM с собственными draft head'ами (для gemma-4/A3B пока
  публичных нет).
- llama-cpp напрямую (после merge PR в апреле 2026) — но это
  отказ от LM Studio UI.

Для нашего use case — ждём пока issue #1597 разрулят. До тех
пор: coder-14b со спек = быстрее, gemma-4 без спек = качественнее,
но не оба сразу.

## Где проседают разные модели

- **gpt-oss-20b** — на тривиальных кейсах (add_docstring, add_type_hints,
  rename_function). Не coder-tuned → не видела SEARCH/REPLACE в pretraining.
- **qwen3.5-9b** — на add_missing_import / remove_unused_import / new-file.
  То есть на правках с пустым SEARCH (`empty SEARCH = create/prepend`)
  и `history-3-turn` (длинный контекст для 9B малый).
- **MoE (35B-a3b)** — массовые отказы на «правка существующего файла».
  General-модели «нормализуют» код при копировании (кавычки, отступы) →
  SEARCH не совпадает byte-for-byte.

## Поведенческие тесты

Все модели проходят: identity, язык, plain-text, native tool emission,
history-after-tool. **Базовое следование инструкциям не зависит от
размера или специализации** в этом ряду — отличия только в структурных
edit-задачах.

## Кто куда подходит

- **gemma-4-26b-a4b** — лучшее качество (24/24), приемлемая скорость
  (~120s бенч). Кандидат на основной агент, если готов терпеть 2.5×
  замедление ради +4% качества.
- **qwen2.5-coder-14b** — лучшая скорость + почти-лучшее качество
  (23/24, 45s со спек). Pareto-выбор «по умолчанию».
- **qwen3.5-9b** — fallback / запасной для low-RAM setup'ов
  (5-6 GB Q4) или если хочется dense general с приемлемым качеством.
- **gpt-oss-20b** — кандидат для plan/review/explain режимов в v0.3
  dual-model setup. Общее рассуждение, не структурный код-edit.
- **qwen3.5/3.6-35b-a3b** — пас. Big general-MoE не оправдывает себя
  на патч-задачах в нашем сетапе.
- **meta-llama-3.1-8b** — пас. 37.5% — низшая планка нашего бенча,
  спек не подключаем (ускорение не лечит провальное качество).
  Llama-семья видела меньше SEARCH/REPLACE / diff формата чем qwen.

См. v0.3 hook «dual-model setup» в `docs/plan.md` — теперь подтверждён
данными.

# Кросс-модельный замер (v0.2)

Бенч-сюита: 24 теста — 15 базовых правок (`test_qwen_produces_applicable_patch`),
multi-file navigation, 7 поведенческих (история, native tools, identity,
язык, plain-text, новый файл, after-tool retention), 1 xfail (grep до
v0.3 native function expansion).

Все прогоны через одну архитектуру (map + native function calling +
SEARCH/REPLACE applier), идентичный harness — отличается только модель.

## Таблица

| модель | размер | arch (tokenizer) | quant | спек | pass | время | tok/s clean |
|---|---|---|---|---|---|---|---|
| **qwen2.5-coder-14b** | 14B dense | qwen2 | Q4_K_M | вкл (draft qwen2-0.5B Q6) | **23/24 (96%)** | **~45s** | ~80 |
| openai/gpt-oss-20b | 20B dense | gpt-oss | MXFP4 | выкл | 21/24 (87.5%) | ~106s | — |
| qwen3.5-9b | 9B dense | qwen35 | Q4_K_M | выкл | 19/24 (79%) | ~73s | 52.5 |
| qwen3.6-35b-a3b | 35B MoE (3B active) | qwen35moe | Q4_K_M | выкл | 13/24 (54%) | ~542s | — |
| qwen3.5-35b-a3b | 35B MoE (3B active) | qwen35moe | Q4_K_M | выкл | 10/24 (42%) | ~303s | 21.4 |

(`arch` и `quant` берутся из LM Studio's `/api/v0/models` — это
tokenizer-семейство и тип квантизации соответственно. `MXFP4` —
microscaling 4-bit формат от OpenAI, GPU-friendly.)

`tok/s clean` = chunks-per-second в стриме после первого токена, на фикс-промте
«Write a Python function that returns the first n primes».

## Чарт отказов

| тест | coder-14b | gpt-oss-20b | qwen3.5-9b | qwen3.5-35b-a3b | qwen3.6-35b-a3b |
|---|---|---|---|---|---|
| add_type_hints | ✓ | ✗ | ✓ | ✓ | ✓ |
| rename_function | ✓ | ✗ | ✓ | ✗ | ✓ |
| add_default_parameter | ✓ | ✓ | ✓ | ✓ | ✓ |
| add_docstring | ✓ | ✗ | ✓ | ✓ | ✓ |
| fix_off_by_one | ✓ | ✓ | ✗ | ✗ | ✗ |
| add_empty_input_guard | ✓ | ✓ | ✓ | ✗ | ✓ |
| replace_format_with_fstring | ✓ | ✓ | ✓ | ✓ | ✗ |
| add_missing_import | ✓ | ✓ | ✗ | ✗ | ✗ |
| wrap_in_try_except | ✓ | ✓ | ✓ | ✗ | ✗ |
| remove_unused_import | ✓ | ✓ | ✗ | ✗ | ✗ |
| add_class_method | ✓ | ✓ | ✓ | ✗ | ✗ |
| change_return_type | ✗ | ✓ | ✓ | ✗ | ✓ |
| convert_list_to_set | ✓ | ✓ | ✓ | ✗ | ✓ |
| add_argument_validation | ✓ | ✓ | ✓ | ✗ | ✓ |
| extract_helper | ✓ | ✓ | ✓ | ✗ | ✗ |
| multi-file navigation | ✓ | ✓ | ✓ | ✗ | ✗ |
| history-2-turn | ✓ | ✓ | ✓ | ✓ | ✓ |
| history-3-turn topic | ✓ | ✓ | ✗ | ✓ | ✓ |
| plain text | ✓ | ✓ | ✓ | ✓ | ✓ |
| identity | ✓ | ✓ | ✓ | ✓ | ✓ |
| русский язык | ✓ | ✓ | ✓ | ✓ | ✓ |
| new file via empty SEARCH | ✓ | ✓ | ✗ | ✗ | ✗ |
| native tool emission | ✓ | ✓ | ✓ | ✓ | ✓ |
| history after tool call | ✓ | ✓ | ✓ | ✓ | ✓ |

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

## По MoE + спек (контекст, не наш замер)

Мы не запускали MoE-модели со спек-декодингом — этот вариант сейчас
заблокирован в LM Studio для Qwen3.5/3.6 dense → A3B target pairing
(см. tracking issue [#1597](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/1597)).
Снаружи (llama.cpp / SGLang / vLLM) поддержка есть, но мы её не
мерили — было вне scope v0.2.

Если в будущем понадобится — переключаться на SGLang с EAGLE3 head
для A3B family. Готовый head для qwen3-coder-30b-a3b есть в
[lmsys/SGLang-EAGLE3-Qwen3-Coder-30B-A3B](https://huggingface.co/lmsys/SGLang-EAGLE3-Qwen3-Coder-30B-A3B-Instruct-SpecForge).

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

- **qwen2.5-coder-14b** — основной агент для патчей. Быстро, точно.
- **qwen3.5-9b** — fallback / запасной для low-RAM setup'ов
  (5-6 GB Q4) или если хочется dense general с приемлемым качеством.
- **gpt-oss-20b** — кандидат для plan/review/explain режимов в v0.3
  dual-model setup. Общее рассуждение, не структурный код-edit.
- **35B-MoE (3.5/3.6)** — пас. Big general-MoE не оправдывает себя
  на патч-задачах в нашем сетапе.

См. v0.3 hook «dual-model setup» в `docs/plan.md` — теперь подтверждён
данными.

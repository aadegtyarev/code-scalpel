# Кросс-модельный замер (v0.2)

Бенч-сюита: 24 теста — 15 базовых правок (`test_qwen_produces_applicable_patch`),
multi-file navigation, 7 поведенческих (история, native tools, identity,
язык, plain-text, новый файл, after-tool retention), 1 xfail (grep до
v0.3 native function expansion).

Все прогоны через одну архитектуру (map + native function calling +
SEARCH/REPLACE applier), идентичный harness — отличается только модель.

## Таблица

| модель | размер | архитектура | спек | pass | время | tok/s clean | TTFT |
|---|---|---|---|---|---|---|---|
| **qwen2.5-coder-14b** | 14B dense | coder-tuned | вкл (draft 0.5B) | **23/24 (96%)** | **~45s** | ~80 (estim.) | <1s |
| gpt-oss-20b | 20B dense | general | выкл | 21/24 (87.5%) | ~106s | — | — |
| qwen3.5-35b-a3b | 35B MoE (3B active) | general | выкл | 10/24 (42%) | ~303s | **21.4** | 2.6s |

`tok/s clean` = chunks-per-second в стриме после первого токена, на фикс-промте
«Write a Python function that returns the first n primes».

## Чарт отказов

| тест | qwen-coder-14b | gpt-oss-20b | qwen3.5-35b-a3b |
|---|---|---|---|
| add_type_hints | ✓ | ✗ | ✓ |
| rename_function | ✓ | ✗ | ✗ |
| add_default_parameter | ✓ | ✓ | ✓ |
| add_docstring | ✓ | ✗ | ✓ |
| fix_off_by_one | ✓ | ✓ | ✗ |
| add_empty_input_guard | ✓ | ✓ | ✗ |
| replace_format_with_fstring | ✓ | ✓ | ✓ |
| add_missing_import | ✓ | ✓ | ✗ |
| wrap_in_try_except | ✓ | ✓ | ✗ |
| remove_unused_import | ✓ | ✓ | ✗ |
| add_class_method | ✓ | ✓ | ✗ |
| change_return_type | ✗ | ✓ | ✗ |
| convert_list_to_set | ✓ | ✓ | ✗ |
| add_argument_validation | ✓ | ✓ | ✗ |
| extract_helper | ✓ | ✓ | ✗ |
| multi-file navigation | ✓ | ✓ | ✗ |
| history-2-turn | ✓ | ✓ | ✓ |
| history-3-turn | ✓ | ✓ | ✓ |
| plain text | ✓ | ✓ | ✓ |
| identity | ✓ | ✓ | ✓ |
| русский язык | ✓ | ✓ | ✓ |
| new file via empty SEARCH | ✓ | ✓ | ✗ |
| native tool emission | ✓ | ✓ | ✓ |
| history after tool call | ✓ | ✓ | ✓ |

## Выводы

**По качеству:** qwen2.5-coder-14b ≫ gpt-oss-20b ≫ qwen3.5-35b-a3b на нашем
бенче.

**По скорости (то же железо, без спек везде кроме qwen-coder):**
- qwen-coder-14b со спек: эталон (×1)
- gpt-oss-20b без спек: **×2.4** медленнее
- qwen3.5-35b-a3b без спек: **×6.7** медленнее

**Distribution > size:** 14B coder-специализированная модель обходит и
20B general (gpt-oss), и 35B MoE general (qwen3.5). Параметры **не главное** —
главное что модель видела в тренировке.

**MoE в LM Studio:** qwen3.5-35b-a3b имеет 3B активных параметров на токен,
но на практике даёт всего 21 tok/s — медленнее ожиданий. LM Studio (на
момент замера) не оптимизирован для MoE-инференса как vLLM. Если запускать
эту модель — лучше через vLLM/SGLang.

**Поведенческие тесты:** все три модели стабильно проходят identity, язык,
plain-text, history (когда вообще проходят основной test set). Это базовое
следование инструкциям — там разрыва нет.

**Где проседает qwen3.5-35b-a3b:** на тестах правок где требуется SEARCH
строго равный source. Большая general-модель часто реструктурирует код
«по-своему» при копировании, что ломает SEARCH/REPLACE.

## Кто куда подходит

- **qwen2.5-coder-14b** — основной агент для патчей. Быстро, точно.
- **gpt-oss-20b** — кандидат для plan/review/explain режимов (общее
  рассуждение, не структурный код-edit).
- **qwen3.5-35b-a3b** — пас. Big general-MoE не оправдывает себя на
  патч-задачах в нашем сетапе.

См. v0.3 hook «dual-model setup» в `docs/plan.md` — теперь подтверждён
данными.

# v0.1 bench — qwen2.5-coder-14b patch stability

Главный вопрос v0.1: *«умеет ли qwen2.5-coder-14b стабильно выдавать применимый patch»*.

## Метод

`tests/test_llm_bench.py` — 15 параметризованных задач разной сложности на
маленьких файлах. Каждый кейс:

1. инициализирует временный git-репо с заданным содержимым
2. вызывает `StepAgent.ask(prompt)` (temperature=0.1, seed=42)
3. применяет полученный patch через `git apply --ignore-whitespace`
4. проверяет пост-состояние (substring/AST)

Запуск: `pytest --run-llm -m llm`. По умолчанию пропускается.

## Результат первого прогона

**12/15 = 80%**.

| # | задача | результат |
|---|---|---|
| 1 | add_type_hints | ✓ |
| 2 | rename_function | ✓ |
| 3 | add_default_parameter | ✗ `git apply failed: greet.py:1` |
| 4 | add_docstring | ✓ |
| 5 | fix_off_by_one | ✓ |
| 6 | add_empty_input_guard | ✓ |
| 7 | replace_format_with_fstring | ✓ |
| 8 | add_missing_import | ✗ `git apply failed: paths.py:0` |
| 9 | wrap_in_try_except | ✓ |
| 10 | remove_unused_import | ✓ |
| 11 | add_class_method | ✗ `git apply failed: user.py:2` |
| 12 | change_return_type | ✓ |
| 13 | convert_list_to_set | ✓ |
| 14 | add_argument_validation | ✓ |
| 15 | extract_helper | ✓ |

## Анализ отказов

Все три отказа — **`git apply failed`**, а не «модель не выдала diff». То есть
content модель понимает, ломается в формате патча.

### `add_missing_import` — несуществующий файл в заголовке

Модель выдала:
```diff
--- a/paths.py
+++ b/paths.py
@@ -0,0 +1 @@
+from pathlib import Path
```

`@@ -0,0 +1 @@` — это «новый файл». Но `paths.py` уже существует.
Правильно было бы `@@ -1,2 +1,3 @@` (или контекст из существующих строк).

### `add_class_method` — пропущен контекст

```diff
--- a/user.py
+++ b/user.py
@@ -2,3 +2,6 @@
     def __init__(self, name):
         self.name = name

+    def greet(self):
+        return f'Hello, {self.name}'
+
```

Hunk начинается с строки 2 (`def __init__`), но игнорирует строку 1
(`class User:`). Без класса в контексте git не находит куда приложить.

### `add_default_parameter` — аналогичная история (greet.py:1)

## Вывод

**Ответ на главный вопрос v0.1: условно «да»** — 80% применимости на
простых задачах. Это значит:

- Инструмент жизнеспособен — большинство патчей применяются с первой попытки
- Но без обвязки (нормализатор, retry, debug-loop) ~1 из 5 запросов
  отвалится на этапе apply

Эти 20% — не «модель тупит», а формат-баги в hunk-заголовках. Их можно
ловить детерминированно:

1. Расширить `patch/normalizer.py`:
   - детектировать `@@ -0,0 +N @@` на существующий файл → пересчитать заголовок
   - детектировать неполный контекст вокруг hunk → добить из исходного файла
2. Добавить retry с фидбеком ошибки git apply (на v0.2 — debug sub-mode)

## Регрессии

Бенч теперь живёт в тестах с маркером `@pytest.mark.llm`. На любую правку
агента/нормализатора/промта прогон `pytest --run-llm -m llm` даст
актуальные цифры и список «новых» отказов.

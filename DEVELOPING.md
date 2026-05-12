# Разработка

Всё что нужно для участия в проекте — на одной странице. README — про
«что это и как пользоваться», `CLAUDE.md` — про то как с проектом
работают AI-агенты, этот файл — про инструменты и правила контрибьютора.

## Стек

| Назначение | Чем | Где конфиг |
|---|---|---|
| Линтер + форматтер | `ruff` (заменяет black + isort + flake8) | `pyproject.toml [tool.ruff]` |
| Типы | `mypy --strict` | `pyproject.toml [tool.mypy]` |
| Тесты | `pytest` + `pytest-asyncio` (auto-mode) | `pyproject.toml [tool.pytest.ini_options]` |
| Покрытие | `pytest-cov` | `pyproject.toml [tool.coverage.run]` |
| Сборка | `hatchling` | `pyproject.toml [build-system]` |

Все конфиги — в `pyproject.toml`, отдельных `.ruff.toml` / `mypy.ini` /
`pytest.ini` нет и не будет. Если ruff/mypy надо поднастроить — правь
секцию в pyproject.

## Установка

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Опционально: `pip install -e ".[diagrams]"` для рендера ```mermaid```
блоков в TUI (нужен также `npm i -g @mermaid-js/mermaid-cli`).

## Перед коммитом

Три зелёных — нет ошибок ни в одной:

```bash
ruff check . && ruff format --check .
mypy code_scalpel/
pytest -x
```

Автофикс мелочи:

```bash
ruff check --fix . && ruff format .
```

Правила:
- `mypy --strict` — все публичные функции/методы аннотированы.
- Тест пишется **вместе** с кодом, не после. Новый модуль без теста
  не коммитим.
- LLM-тесты помечены `@pytest.mark.llm` — гоняются только при
  `pytest --run-llm`, ходят в живой LM Studio.

## Ветки и PR

`main` — только мержи через PR. Никаких прямых коммитов.

```
git switch -c feat/runtime-channel        # новая фича
git switch -c fix/footer-Sure-bug         # баг
git switch -c chore/bump-ruff             # рутина
git switch -c docs/plan-v04               # только docs/
```

Единица PR — **ветка целиком**, не отдельный коммит. В ветке может
быть один коммит или десять — важно что они образуют логически
связанную правку. Промежуточные коммиты вида «typo», «fixup»
лучше перед merge подчистить (`git rebase -i`), но это рекомендация,
не блокер.

Merge-стратегия — обычный merge commit (история ветки сохраняется),
либо rebase-merge если коммиты уже чистые. Squash имеет смысл только
для веток с реально мусорной историей; не дефолт. После merge ветку
удаляем.

В PR описании:
- что меняется и зачем (одно-два предложения);
- ссылка на пункт `docs/plan.md` §31 если задача оттуда;
- результаты probe / тестов если они изменились.

## Релизы и теги

Версии живут в `pyproject.toml`; `code-scalpel --version` читает её
через `importlib.metadata`. Никаких ручных `__version__` строк в
Python-коде — дубли блокируют merge.

Workflow:

1. **открыли версию** (`### v0.X` появилась в `docs/plan.md` §31) —
   PR `chore/open-v0.X` бампит `version` в `pyproject.toml` до
   `0.X.0.dev0`. `--version` теперь честно показывает «эту разработку».
2. **закрыли версию** (заголовок зачёркнут и датирован) — PR
   `chore/release-v0.X` бампит до `0.X.0`, в том же коммите — само
   зачёркивание. После merge:
   ```bash
   git tag v0.X.0 -m "v0.X.0"
   git push --tags
   ```
   На теге создаём GitHub release с changelog'ом — список крупных
   пунктов из закрытого раздела роадмапа.

## CI

Пока вручную (`ruff` + `mypy` + `pytest` локально перед коммитом).
Когда появится remote — добавим GitHub Actions workflow:
lint+types+tests на каждый PR, и автоматический release-черновик
по тегу `v*.*.*`. Это отдельный PR.

## Структура

```
code_scalpel/      — пакет (агент, TUI, runtime, инструменты, индекс…)
tests/             — unit + integration; mocks в tests/mocks.py
scripts/           — диагностика: probe.py, spy_flow.py, бенчи
docs/plan.md       — архитектура + роадмап (источник правды)
docs/article_draft.md — техническая статья
```

## Каналы прогона модели

Запускать модель на проекте можно только через
`code_scalpel.runtime.Runtime` — TUI, `scripts/probe.py`,
`scripts/spy_flow.py` все строят его одинаково. Прямые вызовы
`StepAgent.stream_ask` мимо Runtime ловят пропущенный
`Session.prepare_turn` и дают модели не то что видит юзер.

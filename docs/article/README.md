# Статейная серия про code-scalpel

Папка для сборки серии статей о том, как мы строили TUI coding-агента
для слабой локальной LLM. Финал серии собирается **после того как
проект дойдёт до v0.13+** — сейчас работа идёт в основном репо, в
девлог сюда дописываются главы по мере итераций.

## Файлы

- `v1_devlog.md` — оригинальный сплошной девлог. Источник материала
  для всех статей серии. **Дополняется по ходу проекта.**
- `critic_notes.md` — критика первой версии черновика: «это devlog,
  а не статья», план переработки в фокусированную статью.
- `critic_series.md` — обоснование разбиения на серию из 6 статей.
- `figures/` — графики (генерируются `scripts/figures.py`).
- `articles/` — финальные тексты статей (появятся в финале).

## План серии (по `critic_series.md`)

| # | Тема | Статус | Главы из `v1_devlog.md` |
|---|---|---|---|
| 1 | Вирусная: почему weak-LLM agents ломаются не там, где ожидаешь | planned | 0, 1, 2, 3, 5, 6, 14 (короткие выжимки + единый тезис) |
| 2 | Deep tech: unified diff vs SEARCH/REPLACE | planned | 1, 2, 4 (формат patch'а + native fn calls) |
| 3 | Context engineering: контекст как ресурс | planned | 3, 8, 15, 18 (project_map, navigation, /context view) |
| 4 | Hallucinations: prompt не лечит, данные лечат | planned | 6, 14, 16 (misattribution, post-hoc guard, example trap) |
| 5 | Benchmark локальных моделей для coding | planned | 5, 12 (кросс-модельный бенч, calibration drift) |
| 6 | Архитектура supervised coding-agent | planned | 7, 17, 21, 22, 23, 24, 25, 26, 27, 28, 29 (tool loop, guards, retries, forks, plans) |

Принцип: каждая статья самостоятельна, читается без других. Не
«часть 1, часть 2».

## Графики

В `figures/` лежат три реальных графика по данным
`docs/bench-models.md` (актуальны на 2026-05-13):

| Файл | Что показывает | Назначение |
|---|---|---|
| `fig01_pass_rate_bar.svg` | Pass-rate всех 8 моделей бенча | Статьи 1, 5 |
| `fig02_latency_vs_quality.svg` | Scatter время × качество, Pareto-отметка | Статьи 1, 5 |
| `fig03_three_way_compare.svg` | gemma vs qwen-coder vs gpt-oss инфографика | Статья 5 |

В `scripts/figures.py` есть закомментированные заготовки
`fig_patch_format_evolution` и `fig_token_budget_lazy_context` —
их **не используем как есть** (это синтетика по числам из
девлога). Перед публикацией снимаем реальные числа через
archaeology pass (см. ниже).

## Archaeology pass (когда сядем писать серию)

Сильное замечание читателя: «многие решения побороли давно — лови
ключевые точки, вытаскивай коммиты в worktree, откатывайся и снимай
графики/тесты/скрины как они реально выглядели тогда». Это даёт
честную инженерную истину вместо реконструкции по памяти.

Маппинг ключевых точек → коммиты (для `git worktree add ...`):

| Точка истории | SHA | Что снимать |
|---|---|---|
| До patch-пайплайна (unified diff applier ещё не существует) | `bad1813` | Стартовое состояние, нечего бенчить |
| Unified diff applier + первый бенч 12/15 | `45e1b57` | Прогнать v0.1 bench → 12/15 raw |
| Unified diff + fuzzy fallback (13/15) | (между `45e1b57` и `3020bfb`, найти прямо перед swap'ом) | Прогнать тот же bench → 13/15 |
| Swap на SEARCH/REPLACE (15/15) | `3020bfb` | Тот же bench → 15/15 |
| Native function calling (23/24 на расширенном бенче) | `9a1e3e8` | Расширенный bench → 23/24 |
| Eager context (5-8k токенов на «привет») | до `project_map` рефактора | TUI скрин + token counter |
| Lazy context (~200 токенов на «привет») | после `project_map` рефактора | TUI скрин + token counter |
| Hallucination repro («mark_compacted делает compact») | глава 6 v1_devlog описывает кейс — нужно найти SHA где модель ещё врала на чистый промпт | spy_flow → реальный hallucination payload |
| Post-hoc guard работает | enforce-read-before-show хук | TUI скрин: модель показала код без read_file → ответ отклонён |

**Воркфлоу archaeology pass'а:**

```bash
git worktree add ../scalpel-v0.1 <sha>
cd ../scalpel-v0.1
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# прогнать нужный бенч / запустить TUI / снять скрин
# выгрузить артефакты в основной репо docs/article/figures/historical/
cd -
git worktree remove ../scalpel-v0.1
```

Артефакты складываем в `figures/historical/<tag-or-sha>/` —
чтобы не путать с актуальными.

## Что не идёт в первую статью

Из `critic_notes.md`: подробности Textual UI, ↑↓ history, Mermaid
renderer, /context view UI, FTS5 OR query, token counting,
race conditions в TUI, prompt-регрессии-микро, длинный список
фреймворков на старте. Это материал для статьи 6
(архитектура) или отдельных постов «о TUI».

## Что добавить когда дойдём до текстов

Из критики, ещё не собрано:

- **Mermaid-схемы**: full-context vs tool-based navigation
  (стт 1, 3), agent tool loop (стт 6), prompt rule vs post-hoc
  guard (стт 4), unified diff vs SR (стт 2).
- **TUI screenshots**: tool cards, context view, retry notice,
  patch preview (стт 1, 6) — нужны живые сессии.
- **Hallucination repro screenshot** (стт 4) — через `spy_flow.py`,
  репро кейса из главы 6 девлога.
- **«Wall of pain» с эмоциональным тоном**: «мы были уверены —
  ошиблись», «потратили X часов не туда», «prompt-fix сделал
  хуже», «два execution path жили разной жизнью» и т.п. —
  материал во всех «итерационных» главах девлога, но нужна
  редакторская проходка на тон.
- **Таблица «что думали → что оказалось»** — кросс-главное
  обобщение, редакторская работа.

## Workflow на ближайший период

1. Проект движется по `docs/plan.md` §31 → v0.12.5 (resume) → v0.13.
2. Каждая итерация дополняет `v1_devlog.md` своей главой
   (как мы сделали в v0.12 — главы 26-29).
3. Когда v0.13+ закроется — садимся за серию: разбираем девлог
   по статьям, делаем archaeology pass, рисуем Mermaid-схемы,
   снимаем TUI скрины, пишем тексты.

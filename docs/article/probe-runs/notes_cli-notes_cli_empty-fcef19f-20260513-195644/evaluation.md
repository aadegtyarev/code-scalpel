# Evaluation: notes_cli × v0.10.0 — Fork API landed (для нас неактивно)

## Reached level: **L3** (регресс с L3+ v0.8/v0.9)

Fork API — главное v0.10 — **ортогонален** notes_cli сценарию.
Live probe регрессировал: модель сгенерировала T001 «проанализировать»
(как на v0.7), а не «определить структуру» (как на v0.8/v0.9). 0 write_file.

## One-liner

v0.10: L3, регресс с L3+. Plan-mode выдал T001 «Проанализировать
существующую структуру» — non-actionable как на v0.7. Модель в
code-mode дёрнула project_map(), увидела пусто, сказала «давайте
перейдём к T002» — run_plan пометил T001 skipped и стопнул.
Всего **4 LLM requests, 78s** (минимум серии). Live probe не
получил пользы от v0.10 — Fork API ортогонален «спроектируй с
нуля». Legacy pack: **probe_forks 4/4** (новый), но
**probe_recipes регресс 3/3 → 2/3**.

## По сравнению с v0.9.0

| Метрика | v0.9 | **v0.10** |
|---|---|---|
| reached_level | L3+ | **L3** ↓ |
| LLM requests | 17 | **4** (-76%) |
| prompt_total | 111k | **20k** (-82%) |
| prompt_peak | 8.0k | 6.4k |
| tool_calls | 13 | **4** (-69%) |
| write_file | 4 | **0** ↓ |
| files on disk | 4 (+ tests) | **0** ↓ |
| commits | 0 | 0 = |
| status | 1 failed | **1 skipped** |
| wall_sec | 144 | **78** |

**Регресс в качестве плана** (T001 опять «проанализировать»), не
проблема возможностей. annotate_plan дал T001 Skills: python, но
**не переписал** «Проанализировать» в «Создать структуру» — что
он делал на v0.8/v0.9 успешно. То есть **non-determinism plan-
mode** при той же системной prompt-обвязке.

## Что нового в v0.10

Из git log v0.9.0..v0.10.0:
- **Fork API** — основной landing (видно в legacy probe_forks
  появился). Позволяет агенту порождать sub-сессии для побочных
  задач.
- **Fork в narrow_pass** — annotate_plan теперь может
  use fork-механику.

Все эти изменения **ортогональны** нашему «спроектируй CLI с
нуля» — они не активируются на одной плановой задаче.

## Что произошло на T001

В chat.jsonl видно:
1. Plan: T001 «Проанализировать существующую структуру проекта»,
   `Files: (вызовем project_map())`. **Регресс к v0.7 формату.**
2. annotate_plan x2: добавил `Skills: python`, но не переписал
   Goal/Files.
3. project_map() → видит только pyproject.toml и tests/__init__.py
4. Модель: «Кажется, в проекте есть только pyproject.toml и
   пустой tests. Перейдем к задаче T002.»
5. run_plan: write_file=0 → T001 skipped → stop.

То есть **v0.10 откатил к v0.7 поведению** в plan-mode при том
же системнике. Гипотеза: какие-то изменения в prompts/mode_plan.md
или в `_PLAN_MODE_ADDENDUM` (возможно связанные с fork-context)
сломали action-orientation который v0.8 принёс через annotate_plan.

## Архитектурный smell-check

**v0.10 — это первый явный регресс live-серии**:
- v0.8 принёс прорыв (L3+, 11 write_file, 8 файлов)
- v0.9 закрепил (L3+, дешевле)
- v0.10 откатил к L3 с 0 файлов

При этом legacy axes:
- probe.py: 9/9 = (стабильно)
- probe_code.py: ✓ 1att = (стабильно)
- probe_recipes.py: 3/3 → 2/3 ↓ (регресс!)
- probe_forks.py: 4/4 NEW (новая capability работает)

То есть **новая ось (forks) добавлена красиво, но узкие старые
оси просели**. Это типичная картина «крупной фичи без regression
guard'ов» — что-то в общей prompt-цепочке поменялось при
добавлении fork-логики.

## Что подсветил probe v0.10

Самое интересное наблюдение — **plan-mode non-determinism**.
Та же реплика, тот же системник в основе, но annotate_plan не
переписал T001 в action-oriented форму как раньше. Это значит:
- annotate_plan **не гарантирует** action-orientation
- Чтобы план был воспроизводимо «исполнимым», нужен ещё один слой
  — например, AST-check для TASKS.md (есть ли real-file Files?)

## Legacy probe pack v0.10.0 — новая ось + регресс recipes

| Probe | v0.8 | v0.9 | **v0.10** |
|---|---|---|---|
| `probe.py` | 9/9 | 9/9 | **9/9** = |
| `probe_code.py` | ✓ 1att | ✓ 1att | **✓ 1att** = |
| `probe_recipes.py` | 3/3 | 3/3 | **2/3** ↓ |
| `probe_forks.py` | — | — | **4/4** NEW |

probe_forks **впервые** доступен (Fork API landed) → сразу 4/4
зелёный. Это **сильный аргумент** что fork-инфраструктура хорошо
landed на узком тесте. Но **probe_recipes регрессировал** 3/3 →
2/3 — какая-то recipe-задача сломалась.

Итог v0.10: **расширение capabilities (forks) при цене для plan-
mode generation**. Главный аргумент для статьи — fork-фича landed
изолированно (узкий тест зелёный), но смежные оси (live plan,
recipes) подзаросли. Это normal trade-off большого релиза.

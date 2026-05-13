# Evaluation: notes_cli × v0.6.0

## Reached level: **L1**

То же что v0.3-v0.5. Без прогресса в live четыре версии подряд.

## One-liner

v0.6: L1 reached. `on_tool_executed` hook **появился** для `code_with_retry` (исчезло из adaptations), но модель **сама не дёргает tools** даже когда инфра готова — нужен системник.

## По сравнению с v0.5.0

| Метрика | v0.5 | v0.6 | Δ |
|---|---|---|---|
| reached_level | L1 | L1 | = |
| user_turns | 2 | 2 | = |
| prompt tokens | 7.9k | 8.7k | +10% |
| tool_calls | 0 | 0 | = |
| files on disk | 0 | 0 | = |
| adaptations | 4 | **2** | **−2** |

**Главное:** adaptations схлопнулись с 4 до 2. Исчезли
`code_with_retry.on_tool_executed_missing` и
`code_with_retry.force_loop_missing` — значит между v0.5 и v0.6
эти параметры добавили в `code_with_retry`. Инфраструктурный
рост, но **модель этим не пользуется** — tool calls по-прежнему 0.

## Архитектурный smell-check

**Четвёртая baseline-точка** в одной формации. Понимаем:
- v0.5 был «переходный» — регрессия в legacy показала что-то
  меняли в pipeline
- v0.6 «доделал инфру» (`code_with_retry` принимает параметры),
  но **системник ещё не подтянут**
- Ждём v0.7 (write_file landed) — естественная точка где
  системник должен научить модель пользоваться

## Legacy probe pack v0.6.0 — восстановление + первая «3-attempt» петля

| Probe | v0.3 | v0.4 | v0.5 | **v0.6** |
|---|---|---|---|---|
| `probe.py` | 7/9 | 7/9 | 5/9 ↓ | **8/9** ↑ (рекорд) |
| `probe_code.py` | ✓ 1 attempt | ✓ 1 | ✗ 1 | ✗ **3 attempts** |
| `probe_recipes.py` | n/a | n/a | 2/3 | 2/3 = |

Кривая probe.py: 7 → 7 → 5 → **8**. То есть v0.5 был транзитный
дно, v0.6 восстановил и превзошёл baseline на 1 балл.

`probe_code.py` интересно: на v0.5 было 1 attempt и red, на v0.6
**3 attempts** и всё ещё red. То есть `code_with_retry` теперь
действительно крутит retry-цикл (раньше один прогон + rollback),
но **модель повторяет тот же неверный SR три раза**. Это
**типичная картина 14b на iterative_loop без semantic anti-loop'а** —
которое мы добавили только в v0.9 (machine guards).

## Список дальнейших действий

- v0.7 — главное ожидание: write_file + видимо системник под него.
  Должно перевести в L3 (модель прыгнет на write_file как
  простой канал, минуя L2 через SR).

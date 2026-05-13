# Historical Playbook — пошаговая операционка на одну версию

Один и тот же чек-лист на каждый тэг от v0.3 до main. Артефакты
обоих типов (live + legacy) ложатся в `docs/article/probe-runs/`
основного репо через symlink.

## 0. Перед серией (один раз)

- LM Studio запущена с `qwen/qwen2.5-coder-14b` на `localhost:1234`
- Основной репо в чистом состоянии — `git status --porcelain` пусто
- Никаких параллельных probe-демонов: `pgrep -fa scripts.probes_v2.daemon`
- `lms ps` показывает qwen-14b (baseline)

## 1. Подготовка worktree

```bash
TAG=v0.X.Y
WORKTREE=../scalpel-${TAG}

git worktree add ${WORKTREE} ${TAG}
mkdir -p ${WORKTREE}/scripts ${WORKTREE}/docs/article

# Копируем актуальный probe-инструментарий из main репо.
# Старые версии не имели probes_v2/ — нам нужен runner main'а.
cp -r scripts/probes_v2 ${WORKTREE}/scripts/
cp scripts/__init__.py ${WORKTREE}/scripts/

# Симлинк на artefact-папку основного репо — артефакты сразу
# в git'е main, не размазаны по worktree.
ln -s "$(pwd)/docs/article/probe-runs" ${WORKTREE}/docs/article/probe-runs

# venv в worktree → scalpel = код тэга
cd ${WORKTREE}
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]" --quiet
```

## 2. Live-прогон (одна базовая задача)

Из ${WORKTREE}:

```bash
python -m scripts.probes_v2.cli start notes_cli notes_cli_empty
# → печатает run-id, запоминаем
```

Затем серия `step` с **той же первой репликой** на каждом тэге
(см. `scenarios/notes_cli.md`):

```bash
python -m scripts.probes_v2.cli step <run-id> "хочу собрать python-CLI для заметок: команды add, list, search, delete. json-storage, pytest. спроектируй и реализуй с тестами. если есть архитектурные вопросы — задай." --mode ask
```

Дальше реагируем по reference-таблице в `scenarios/notes_cli.md`.
Reply на каждом ходу — короткий, в `user_tone_of_voice.md` стиле,
не диктуем решения.

**Стоп-условия:**
- scalpel дошёл до L5+ (TASKS.md выполнен через `/go`) → `task_solved`
- scalpel остановился сам / 15+ turn'ов / семантическая петля → `user_gave_up`
- инфраструктурная ошибка → `error`

```bash
python -m scripts.probes_v2.cli finalize <run-id> --reason=<task_solved|user_gave_up|error>
```

Затем я (Claude) пишу `evaluation.md` по шаблону из `PROTOCOL.md`,
указываю `reached_level`.

## 3. Legacy probe pack (после live, или параллельно если LM Studio свободна)

Из того же worktree:

```bash
python -m scripts.probes_v2.legacy_pack ${TAG}
```

Гоняет `probe.py`, `probe_code.py`, `probe_recipes.py`,
`probe_forks.py`, `probe_fork_reviewer.py`, `probe_e2e_forks.py`.
На ранних тэгах часть из них **отсутствует** в `scripts/` — это
data, не ошибка (`status: skipped`).

Артефакты: `docs/article/probe-runs/legacy/${TAG}/`:
- `<probe>.txt` — stdout/stderr/exit_code каждого
- `summary.json` — агрегат с `pass_rate_guess` где удалось распарсить

## 4. Cleanup

```bash
cd /path/to/main/repo
git worktree remove ${WORKTREE} --force
# venv внутри удалится вместе с worktree
```

Артефакты остались в основном репо благодаря symlink'у. Коммитим:

```bash
git add docs/article/probe-runs/
git commit -m "historical: ${TAG} — L<N> reached, legacy pack done"
git push
```

## 5. Перед следующим тэгом

- `lms ps` → убеждаемся что qwen-14b всё ещё baseline (а не gemma
  застряла от swap-теста)
- Если нет: `lms unload <other> && lms load qwen/qwen2.5-coder-14b`
- `pgrep -fa scripts.probes_v2.daemon` → ноль активных

## Порядок прохода

**От старого к новому** — v0.3.0 → v0.4.0 → v0.5.0 → ... → main.
Это даёт «как меняется до» сразу видно перед прогоном следующей.

На каждом тэге:
1. Live notes_cli (одна базовая реплика, реакция по `scenarios/notes_cli.md`)
2. Legacy probe pack
3. evaluation.md с reached_level + сравнением с предыдущим тэгом
4. Commit + переход

## Краткая отчётность для каждой версии (в evaluation.md)

```markdown
## Reached level: L<N>

## По сравнению с предыдущим тэгом (vX.Y-1)
- Что улучшилось: ...
- Что осталось так же: ...
- Что регрессировало: ...

## Legacy pack
- probe_code: <N>/24 (на vX.Y-1 было <M>/24)
- probe_forks: ... (если уже есть)
- ...
```

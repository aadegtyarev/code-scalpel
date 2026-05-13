# Historical Playbook — пошаговая операционка на одну версию

Один и тот же чек-лист на каждый тэг от v0.3 до main. Артефакты
ложатся в `docs/article/probe-runs/` основного репо через symlink.

## Главный workflow — plan → go

**Каноническая последовательность** (повторяет TUI: `/mode plan`
→ задача → `/loop` → `/go`):

1. `probe step --mode plan` с базовой задачей → модель пишет
   TASKS.md в DSL, `_maybe_save_plan` сохраняет автоматически
2. **Проверить** что TASKS.md сохранился. Если нет — корректирующий
   plan-turn с явной просьбой формата (это не подсказка про
   содержание, это про DSL)
3. `probe go <run-id>` → `agent.run_plan()` ходит по TASKS.md
4. `probe finalize` — собираем артефакты и mechcheckers

См. подробное описание сценария в `scenarios/notes_cli.md`.

## Capabilities matrix по версиям

| Версия | Tools | mode_addenda | `iterative_patch_loop` | slash | Особенности |
|---|---|---|---|---|---|
| v0.3.0 | 9 | plan, code | False (default OFF) | `/run` | базовый MVP, нет write_file |
| v0.5.0 | 10 | plan, code | False | `/run` | + retrieve tool (?) |
| v0.6.0 | 10 | + 2 (review?) | False | **`/go`** (rename) | переход name |
| v0.7.0 | **15** (+5) | 6 (+2) | False | `/go` | **write_file**, project_map, bwrap |
| v0.8.0 | 15 | 6 | False | `/go` | narrow passes, annotate_plan |
| v0.9.0 | 15 | 6 | False | `/go` | machine guards (files/tests/commit) |
| v0.10.0 | 15 | 6 | False | `/go` | Fork API |
| v0.11.0 | 15 | 6 | False | `/go` | ReviewedAuto fork |
| v0.12.0 | **16** (+1) | 6 | False | `/go` + `/escalate` | UpstreamPendingQueue, swap |

**Главное:** `iterative_patch_loop` по умолчанию **выключен на
всех версиях**. В probe мы передаём `force_loop=True` через
`code_with_retry` kwargs. На v0.3-v0.4 этот kwarg отсутствует →
compat-shim в `daemon._compat_call` его отбросит → retry-loop
не сработает. Это **фиксируется как наблюдение**, не лечится.

## 0. Перед серией (один раз)

- LM Studio запущена с `qwen/qwen2.5-coder-14b` на `localhost:1234`
- `lms ps` показывает qwen-14b
- Основной репо в чистом состоянии
- Нет других probe-демонов: `pgrep -fa scripts.probes_v2.daemon`

## 1. Подготовка worktree

```bash
TAG=v0.X.Y
WT=../scalpel-${TAG}

git worktree add ${WT} ${TAG}
mkdir -p ${WT}/scripts ${WT}/docs/article
cp -r scripts/probes_v2 ${WT}/scripts/
cp scripts/__init__.py ${WT}/scripts/
ln -s "$(pwd)/docs/article/probe-runs" ${WT}/docs/article/probe-runs

cd ${WT}
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]" --quiet
```

## 2. Запуск probe (один и тот же на всех версиях)

```bash
ID=$(python -m scripts.probes_v2.cli start notes_cli notes_cli_empty)
echo "run-id: $ID"
```

`user_plan.md` в `docs/article/probe-runs/$ID/` я пишу перед
первым step'ом — что ожидаю, как буду реагировать на типичные
ходы scalpel'а.

## 3. Step 1: plan

```bash
python -m scripts.probes_v2.cli step $ID "хочу собрать python-CLI для заметок: команды add, list, search, delete. json-storage, pytest. спроектируй и реализуй с тестами. если есть архитектурные вопросы — задай." --mode plan
```

## 4. Проверка TASKS.md

```bash
ls docs/article/probe-runs/$ID/.workdir/.code-scalpel/TASKS.md
```

- Файл есть → идём на `probe go`
- Файла нет → даём корректирующий plan-turn:
  ```bash
  python -m scripts.probes_v2.cli step $ID "не понял — пиши именно в формате как у нас принято: ## T001: <title> с полями Files / Acceptance / Test command. 3-7 задач." --mode plan
  ```
  Если после двух plan-turn'ов TASKS.md так и нет → фиксируем
  L1 (план в reply, но не в DSL) → финализируем `partial`,
  `probe go` уже не запускаем (нет смысла).

## 5. Step: go

```bash
python -m scripts.probes_v2.cli go $ID
```

Печатает `stopped_reason` + список outcomes. Возможные:
- `all_done` → весь план выполнен → L5 (потом ещё pytest зелёный?)
- `max_failures` → застряло на N-й задаче → L3-L4
- `no_tasks` → TASKS.md не было (значит и не должны были звать go)
- `plan_modified` → промежуточная редакция TASKS.md (вряд ли у нас)

## 6. Finalize

```bash
python -m scripts.probes_v2.cli finalize $ID --reason=<task_solved|user_gave_up|error>
```

## 7. Evaluation

Я пишу `evaluation.md` в `docs/article/probe-runs/$ID/` по
шаблону из PROTOCOL.md. Главное — указать `reached_level` и
сравнение с предыдущей версией.

## 8. Legacy probe pack

Параллельно (или после live):

```bash
python -m scripts.probes_v2.legacy_pack ${TAG}
```

Артефакты в `docs/article/probe-runs/legacy/${TAG}/`.

## 9. Cleanup

```bash
cd /path/to/main/repo
git worktree remove ${WT} --force
```

Артефакты остались в main репо через symlink. Коммитим:

```bash
git checkout -b probe/historical-${TAG}
git add docs/article/probe-runs/
git commit -m "probe: historical ${TAG} — L<N> reached"
git push -u origin probe/historical-${TAG}
gh pr create --title "probe: historical ${TAG}" --body "..."
gh pr merge --merge --delete-branch
git checkout main && git pull
```

## Перед следующим тэгом

- `lms ps` → qwen-14b baseline
- `pgrep -fa scripts.probes_v2.daemon` → ноль активных
- `git status --porcelain` → чисто

## Порядок прохода

**От v0.3.0 к main** по нарастающей. На каждом тэге **одни и те
же** реплики и команды (см. секцию 3-6). Сравнение всегда
«новый со старым» в evaluation.md.

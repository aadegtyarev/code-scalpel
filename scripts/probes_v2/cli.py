"""Probe-suite v2 CLI.

Команды:
  probe start <scenario> <project>     — создать run-dir и запустить демон
  probe step <run-id> "<text>"         — отправить реплику юзера
  probe note <run-id> "<text>"         — дописать в notes.md
  probe status <run-id>                — счётчики (для интерактивного чтения)
  probe finalize <run-id> --reason=... — остановить демон + собрать артефакты
  probe list                           — все прогоны из INDEX.md

Поведение по слоям зафиксировано в `PROTOCOL.md`. Все ошибки —
с явным человеческим текстом в stderr и ненулевым exit code.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from scripts.probes_v2.ipc import send_request
from scripts.probes_v2.state import (
    FIXTURES_ROOT,
    PROBE_RUNS_ROOT,
    SCENARIOS_ROOT,
    RunPaths,
    current_git_sha,
    git_is_dirty,
    git_remote_url,
    make_run_id,
    utc_now,
    write_placeholder_artifacts,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Probe-suite v2 — живые прогоны со scalpel-агентом.",
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Пин модели для всех probe-прогонов. Меняется только когда мы
# **намеренно** проверяем другую модель (например, gemma как
# upstream-победитель в свапе). Auto/local-model запрещены —
# нужен явный id для reproducibility.
PINNED_BASE_MODEL = "qwen/qwen2.5-coder-14b"
PINNED_UPSTREAM_MODEL_DEFAULT = "gemma-4-26b-a4b-it-assistant"


@app.command()
def start(
    scenario: Annotated[
        str, typer.Argument(help="ID сценария — файл в scripts/probes_v2/scenarios/")
    ],
    project: Annotated[
        str, typer.Argument(help="Имя fixture-проекта в scripts/probes_v2/fixtures/")
    ],
    upstream_model: Annotated[
        str | None,
        typer.Option(
            "--upstream-model",
            help="Имя upstream-модели для делегирования сложных fork'ов (v0.12 UpstreamForker). "
            "Например `gemma-4-26b-a4b`. Если задано — fork-резолвер делегирует наверх; "
            "если нет — всё на основной модели.",
        ),
    ] = None,
) -> None:
    """Создать run-dir, развернуть fixture, запустить демон.
    Печатает run-id на stdout — caller сохраняет его для
    последующих `step` / `finalize`."""
    scenario_path = REPO_ROOT / SCENARIOS_ROOT / f"{scenario}.md"
    fixture_path = REPO_ROOT / FIXTURES_ROOT / project
    if not scenario_path.is_file():
        typer.echo(f"error: scenario not found: {scenario_path}", err=True)
        raise typer.Exit(2)
    if not fixture_path.is_dir():
        typer.echo(f"error: fixture not found: {fixture_path}", err=True)
        raise typer.Exit(2)

    git_sha = current_git_sha(REPO_ROOT)
    git_dirty = git_is_dirty(REPO_ROOT)
    remote_url = git_remote_url(REPO_ROOT)
    git_commit_url = (
        f"{remote_url}/commit/{git_sha}" if remote_url and git_sha != "unknown" else None
    )
    run_id = make_run_id(scenario, project, git_sha)
    run_dir = REPO_ROOT / PROBE_RUNS_ROOT / run_id
    paths = RunPaths(run_dir)
    write_placeholder_artifacts(paths)

    # scenario.md — копия в каждый прогон, чтобы исторический run
    # помнил какой именно версии сценарий он играл.
    paths.scenario_md.write_text(scenario_path.read_text())

    # workdir — рабочая копия fixture'ы, отдельно от run-dir
    # (внутри run-dir хранится tar.gz снапшота, не «живая» копия).
    workdir = paths.workdir
    if workdir.exists():
        shutil.rmtree(workdir)
    shutil.copytree(fixture_path, workdir)

    # scalpel ожидает что cwd — git-репо (commits_landed мехчекер,
    # auto_git в config). Инициализируем чистый репо со стартовым
    # commit'ом — fixture получает свежий git, всё что добавит
    # модель будет «после» init-коммита и легко считается через
    # `git rev-list HEAD ^<init-sha>`.
    _init_workdir_git(workdir)

    # Tar.gz «начального» состояния — для сценариев которые
    # стартуют с пустой папки tar просто пустой. Берём fixture,
    # не workdir — они идентичны на этом этапе, и tar.gz fixture'ы
    # совпадает между прогонами одного project'а (хорошо для diff).
    with tarfile.open(paths.fixture_tar, "w:gz") as tar:
        tar.add(fixture_path, arcname=project)

    # Дёрнем `/v1/models` чтобы зафиксировать реально загруженную
    # модель — не угадывать в meta. Если LM Studio недоступна —
    # фиксируем как «unknown», прогон не блокируем (агент сам
    # упадёт на первом step с осмысленным error). Если загружено
    # не PINNED_BASE_MODEL — печатаем warning, но прогон
    # продолжаем (могут быть кейсы где пользователь намеренно
    # сменил модель).
    base_url = "http://localhost:1234/v1"
    model_loaded = _detect_lmstudio_model(base_url)
    all_loaded = _lmstudio_loaded_model_ids(base_url) or []
    if model_loaded not in {PINNED_BASE_MODEL, "unknown"} and not upstream_model:
        typer.echo(
            f"warning: LM Studio loaded `{model_loaded}`, probe expects "
            f"`{PINNED_BASE_MODEL}`. Continuing — verify intent in evaluation.md.",
            err=True,
        )
    # Проверка upstream-модели — если задана, она должна быть
    # **тоже** загружена в LM Studio. Иначе fork'и в очереди
    # упадут при flush'е на 404/timeout. Это **критично**, поэтому
    # fail-fast (а не warning) — иначе бессмысленно жечь токены
    # baseline-задачами.
    if upstream_model and upstream_model not in all_loaded:
        typer.echo(
            f"error: upstream model `{upstream_model}` not loaded in LM Studio.\n"
            f"Currently loaded: {', '.join(all_loaded) if all_loaded else '(none / API unreachable)'}.\n"
            f"Load it via LM Studio UI (или `lms load {upstream_model}` если CLI стоит) и повторите.",
            err=True,
        )
        raise typer.Exit(1)

    upstream_cmd_part = f" --upstream-model={upstream_model}" if upstream_model else ""
    meta = {
        "run_id": run_id,
        "scenario": scenario,
        "project": project,
        "version_tag": f"main_{git_sha[:7]}" if git_sha != "unknown" else "unknown",
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "git_commit_url": git_commit_url,
        "git_checkout_cmd": f"git checkout {git_sha}" if git_sha != "unknown" else None,
        "model_name_expected": PINNED_BASE_MODEL,
        "model_name_actual": model_loaded,
        "model_base_url": base_url,
        # None = без upstream, всё решает основная модель; имя
        # модели = делегируем сложные fork'и наверх. v0.12
        # `UpstreamForker` + `UpstreamPendingQueue` обеспечивают
        # батчинг через `/escalate` или конец /go.
        "upstream_model": upstream_model,
        "started_at": utc_now(),
        "ended_at": None,
        "ended_reason": None,
        "user_role": "claude-acting-as-user-per-tone-of-voice.md",
        "command": f"probe start {scenario} {project}{upstream_cmd_part}",
    }
    paths.meta_json.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

    # Запускаем демон. start_new_session=True отвязывает его от
    # текущего TTY — closing CLI не убьёт демон.
    import os as _os

    env = _os.environ.copy()
    env["PROBE_BASE_MODEL"] = PINNED_BASE_MODEL
    if upstream_model:
        env["PROBE_UPSTREAM_MODEL"] = upstream_model
    proc = subprocess.Popen(
        [sys.executable, "-m", "scripts.probes_v2.daemon", str(run_dir), str(workdir)],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )

    # Демон должен записать .daemon.json с PID+портом — ждём
    # появления файла до 10 сек. Если не записал — что-то
    # сломалось при старте, сообщаем.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if paths.daemon_info.exists():
            break
        if proc.poll() is not None:
            typer.echo(
                f"error: daemon exited before signalling readiness (rc={proc.returncode})",
                err=True,
            )
            raise typer.Exit(1)
        time.sleep(0.1)
    else:
        typer.echo("error: daemon did not signal readiness within 10s", err=True)
        proc.terminate()
        raise typer.Exit(1)

    typer.echo(run_id)


@app.command()
def step(
    run_id: Annotated[str, typer.Argument()],
    text: Annotated[str, typer.Argument(help="Реплика юзера (от моего, Claude, лица)")],
) -> None:
    """Отправить реплику демону, получить ответ scalpel'а."""
    paths = _resolve_run(run_id)
    host, port = _daemon_info(paths)
    response = send_request(host, port, {"op": "step", "text": text})
    if not response.get("ok"):
        typer.echo(f"error: {response.get('error', 'unknown')}", err=True)
        raise typer.Exit(1)
    typer.echo(response["reply"])


@app.command()
def note(
    run_id: Annotated[str, typer.Argument()],
    text: Annotated[str, typer.Argument()],
) -> None:
    """Свободная заметка в notes.md с timestamp'ом."""
    paths = _resolve_run(run_id)
    host, port = _daemon_info(paths)
    response = send_request(host, port, {"op": "note", "text": text})
    if not response.get("ok"):
        typer.echo(f"error: {response.get('error', 'unknown')}", err=True)
        raise typer.Exit(1)


@app.command()
def status(run_id: Annotated[str, typer.Argument()]) -> None:
    """Текущие счётчики прогона: turns, tool calls, wall time."""
    paths = _resolve_run(run_id)
    host, port = _daemon_info(paths)
    response = send_request(host, port, {"op": "status"})
    typer.echo(json.dumps(response, indent=2, ensure_ascii=False))


@app.command()
def finalize(
    run_id: Annotated[str, typer.Argument()],
    reason: Annotated[
        str,
        typer.Option(
            "--reason",
            help="task_solved | user_gave_up | error",
        ),
    ],
) -> None:
    """Остановить демон, снять snapshot финального дерева,
    обновить metrics/verdict, дописать в INDEX.md."""
    if reason not in {"task_solved", "user_gave_up", "error"}:
        typer.echo(f"error: bad --reason: {reason}", err=True)
        raise typer.Exit(2)
    paths = _resolve_run(run_id)
    host, port = _daemon_info(paths)
    response = send_request(host, port, {"op": "stop"})
    if not response.get("ok"):
        typer.echo(f"warning: daemon stop returned: {response}", err=True)
    # Даём демону до 5 сек на shutdown
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and paths.daemon_info.exists():
        time.sleep(0.1)

    # Снапшот workdir → final_tree (раскрытый, не tar.gz —
    # удобно `grep`/`ls` в репо). Исключаем `.git` чтобы он не
    # попал в основной репо как gitlink (вложенный submodule
    # pointer, который git не клонирует).
    if paths.workdir.exists():
        if paths.final_tree.exists():
            shutil.rmtree(paths.final_tree)
        shutil.copytree(
            paths.workdir,
            paths.final_tree,
            ignore=shutil.ignore_patterns(".daemon.json", ".git"),
        )
        # Workdir вне репо ниже probe-runs/<id>/.workdir — удаляем
        # после снапшота, чтобы не таскать дубликат.
        shutil.rmtree(paths.workdir)

    # Обновим meta: ended_at + ended_reason
    meta = json.loads(paths.meta_json.read_text())
    meta["ended_at"] = utc_now()
    meta["ended_reason"] = reason
    paths.meta_json.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

    # Verdict — пока заглушка с reason'ом. Мехчекеры подключим
    # отдельным PR'ом вместе с конкретным сценарием.
    verdict = json.loads(paths.verdict_json.read_text())
    verdict["scenario"] = meta["scenario"]
    verdict["ended_reason"] = reason
    paths.verdict_json.write_text(json.dumps(verdict, indent=2, ensure_ascii=False) + "\n")

    # Дописать в INDEX.md одну строку.
    _append_to_index(meta, verdict, paths)

    typer.echo(f"finalized: {run_id} ({reason})")


@app.command(name="list")
def list_runs() -> None:
    """Вывести содержимое INDEX.md (просто `cat`)."""
    index = REPO_ROOT / PROBE_RUNS_ROOT / "INDEX.md"
    if not index.exists():
        typer.echo("no INDEX.md yet")
        raise typer.Exit(0)
    typer.echo(index.read_text())


# ── helpers ──────────────────────────────────────────────────────


def _resolve_run(run_id: str) -> RunPaths:
    run_dir = REPO_ROOT / PROBE_RUNS_ROOT / run_id
    if not run_dir.is_dir():
        typer.echo(f"error: run not found: {run_dir}", err=True)
        raise typer.Exit(2)
    return RunPaths(run_dir)


def _daemon_info(paths: RunPaths) -> tuple[str, int]:
    """Возвращает (host, port) — типизировано отдельно от raw
    JSON чтобы mypy видел чёткие типы в каждой команде CLI."""
    if not paths.daemon_info.exists():
        typer.echo(
            f"error: daemon not running (no .daemon.json in {paths.run_dir})",
            err=True,
        )
        raise typer.Exit(1)
    try:
        raw = json.loads(paths.daemon_info.read_text())
        return str(raw["host"]), int(raw["port"])
    except (OSError, KeyError, json.JSONDecodeError) as e:
        typer.echo(f"error: cannot read daemon info: {e}", err=True)
        raise typer.Exit(1) from None


def _append_to_index(meta: dict[str, object], verdict: dict[str, object], paths: RunPaths) -> None:
    """Дописать строку в `docs/article/probe-runs/INDEX.md` под
    таблицей. Колонки: run-id / date / scenario / project /
    version / verdict / turns / tokens / one-liner."""
    metrics = json.loads(paths.metrics_json.read_text())
    turns = metrics.get("user_turns", 0)
    prompt_t = metrics.get("prompt_tokens_total", 0)
    comp_t = metrics.get("completion_tokens_total", 0)
    total_k = (prompt_t + comp_t) // 1000
    one_liner = _extract_one_liner(paths.evaluation_md)
    date = (
        datetime.fromisoformat(str(meta.get("started_at", ""))[:-1] + "+00:00")
        .astimezone(UTC)
        .date()
        .isoformat()
    )
    commit_cell = _commit_cell(meta)
    row = (
        f"| `{meta['run_id']}` | {date} | {meta['scenario']} | {meta['project']} "
        f"| {commit_cell} | {verdict.get('ended_reason')} "
        f"| {turns} | {total_k}k | {one_liner} |\n"
    )
    index = REPO_ROOT / PROBE_RUNS_ROOT / "INDEX.md"
    text = index.read_text() if index.exists() else ""
    # Найти строку-заглушку «(пока пусто…)» и заменить, или
    # просто дописать в конец таблицы.
    placeholder = "| _(пока пусто — первый прогон ещё не сделан)_ | | | | | | | | |"
    text = text.replace(placeholder, row.rstrip("\n")) if placeholder in text else text + row
    index.write_text(text)


def _init_workdir_git(workdir: Path) -> None:
    """Свежий git-репо внутри workdir со стартовым коммитом
    «probe-fixture initial state». user.name / user.email
    локально (не глобально) — чтобы probe не подтягивал
    личные данные пользователя из ~/.gitconfig."""
    env = {"GIT_TERMINAL_PROMPT": "0"}
    subprocess.run(
        ["git", "init", "-q"], cwd=workdir, check=True, env={**__import__("os").environ, **env}
    )
    subprocess.run(
        ["git", "config", "user.email", "probe@code-scalpel.local"],
        cwd=workdir,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "code-scalpel probe"],
        cwd=workdir,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=workdir, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "probe-fixture initial state"],
        cwd=workdir,
        check=True,
    )


def _detect_lmstudio_model(base_url: str) -> str:
    """GET <base_url>/models, читаем первый загруженный id.
    Возвращаем строку имени модели как её отдаёт LM Studio. На
    сетевые ошибки — `"unknown"` (caller не блокируем, scalpel
    сам отчитается при первом step'е).

    LM Studio v0.3+ имеет состояние `state: "loaded"`; пытаемся
    предпочесть его, если поле есть. Иначе — первая запись."""
    loaded = _lmstudio_loaded_model_ids(base_url)
    if loaded is None:
        return "unknown"
    return loaded[0] if loaded else "unknown"


def _lmstudio_loaded_model_ids(base_url: str) -> list[str] | None:
    """Возвращает список id моделей которые сейчас доступны через
    `/v1/models`. None при сетевой ошибке (LM Studio недоступна).
    `state: loaded` предпочтительнее, но если LM Studio не отдаёт
    state (старые версии) — отдаём все id."""
    try:
        with urllib.request.urlopen(f"{base_url}/models", timeout=3) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    items = data.get("data") or []
    if not items:
        return []
    has_state = any("state" in m for m in items)
    if has_state:
        return [str(m.get("id")) for m in items if m.get("state") == "loaded" and m.get("id")]
    return [str(m.get("id")) for m in items if m.get("id")]


def _commit_cell(meta: dict[str, object]) -> str:
    """Колонка INDEX.md `commit`: `[sha7](url)` если есть remote
    + `⚠️ dirty` маркер если репо был грязный на момент прогона
    (значит `git checkout <sha>` не воспроизведёт состояние)."""
    sha = str(meta.get("git_sha", "unknown"))
    url = meta.get("git_commit_url")
    sha7 = sha[:7] if sha != "unknown" else "unknown"
    cell = f"[`{sha7}`]({url})" if url else f"`{sha7}`"
    if meta.get("git_dirty"):
        cell += " ⚠️dirty"
    return cell


def _extract_one_liner(evaluation_md: Path) -> str:
    """Достать одну фразу из секции `## One-liner` evaluation.md.
    Если её ещё нет (я не написал) — возвращаем «_(нет one-liner)_»."""
    if not evaluation_md.exists():
        return "_(нет evaluation)_"
    text = evaluation_md.read_text()
    marker = "## One-liner"
    idx = text.find(marker)
    if idx < 0:
        return "_(нет one-liner)_"
    body = text[idx + len(marker) :].strip().split("\n##", 1)[0].strip()
    # Сократить до одной строки + убрать markdown italic
    one = body.split("\n")[0].strip()
    if one.startswith("_(") or not one:
        return "_(нет one-liner)_"
    # Убрать `|` чтобы не сломать markdown-таблицу
    return one.replace("|", "/")


if __name__ == "__main__":
    app()

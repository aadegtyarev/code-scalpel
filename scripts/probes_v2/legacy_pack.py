"""Runner для готовых `scripts/probe_*.py` на текущей версии.

Использование (изнутри worktree-тэга):
    python -m scripts.probes_v2.legacy_pack v0.X.Y

Гонит каждый probe из набора, ловит stderr/stdout, пишет в
`docs/article/probe-runs/legacy/<tag>/{probe_name}.txt` плюс
агрегатный `summary.json` с метриками которые удалось распарсить.

Probe'ы которых нет на этом тэге (probe_forks появился позже,
например) — отмечаются как `skipped: not_found_at_this_tag`. Это
данные, не ошибка.

LM Studio должна быть запущена с qwen/qwen2.5-coder-14b — это
требование probe-скриптов наследуется как есть."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_OUT_ROOT = REPO_ROOT / "docs" / "article" / "probe-runs" / "legacy"

# Probe'ы в порядке от самых старых (есть везде) к новым (только
# на поздних тэгах). На раннем тэге часть их просто отсутствует
# в `scripts/` — пишем skipped.
PROBES = [
    "probe.py",
    "probe_code.py",
    "probe_recipes.py",
    "probe_forks.py",
    "probe_fork_reviewer.py",
    "probe_e2e_forks.py",
]

# Регексы для парсинга "сколько прошло / всего" из stdout
# каждого probe. Не идеальные — лучше чем ничего.
RE_PASS_RATE = re.compile(r"(\d+)\s*/\s*(\d+)")
RE_SUMMARY_LINE = re.compile(r"=== SUMMARY ===|=== RESULT", re.MULTILINE)


def _run_probe(name: str, out_dir: Path, timeout: float = 600) -> dict[str, object]:
    """Один probe. Запускаем как обычный python-скрипт из repo
    root (чтобы CWD совпадало с тем как probes обычно стартуют)."""
    script = REPO_ROOT / "scripts" / name
    if not script.is_file():
        return {"name": name, "status": "skipped", "reason": "not_found_at_this_tag"}

    out_file = out_dir / f"{name}.txt"
    started = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "timeout", "duration_sec": timeout}
    duration = round(time.monotonic() - started, 2)

    body = (
        f"# {name}\n"
        f"# exit_code={result.returncode}\n"
        f"# duration_sec={duration}\n\n"
        "## stdout\n\n"
        f"{result.stdout}\n\n"
        "## stderr\n\n"
        f"{result.stderr}\n"
    )
    out_file.write_text(body)

    # Грубый парс «N/M» — берём последнее совпадение в stdout,
    # это обычно итоговая строка summary.
    matches = RE_PASS_RATE.findall(result.stdout)
    pass_rate: tuple[int, int] | None = None
    if matches:
        passed, total = matches[-1]
        try:
            pass_rate = (int(passed), int(total))
        except ValueError:
            pass_rate = None

    return {
        "name": name,
        "status": "ok" if result.returncode == 0 else "non_zero_exit",
        "exit_code": result.returncode,
        "duration_sec": duration,
        "pass_rate_guess": list(pass_rate) if pass_rate else None,
        "stdout_path": str(out_file.relative_to(REPO_ROOT)),
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m scripts.probes_v2.legacy_pack <tag-or-label>", file=sys.stderr)
        return 2
    tag = argv[1]
    out_dir = LEGACY_OUT_ROOT / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, object]] = []
    for probe in PROBES:
        print(f"● {probe}…", file=sys.stderr, flush=True)
        result = _run_probe(probe, out_dir)
        summary.append(result)
        print(f"  → {result.get('status')}", file=sys.stderr)

    summary_path = out_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "tag": tag,
                "ran_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "probes": summary,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    print(f"\nLegacy pack done → {summary_path.relative_to(REPO_ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

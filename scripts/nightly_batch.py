"""Ночной N-прогон notes_cli против удалённой LM Studio.

Последовательно гоняет N полных циклов start→plan→go→finalize,
собирает механические вердикты и печатает агрегат. Прогоны
последовательны — одна модель на одном сервере.

Не часть пакета; запускается руками:
    .venv/bin/python scripts/nightly_batch.py <N> <base_url> <out.jsonl>
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable
CLI = [PY, "-m", "scripts.probes_v2.cli"]
TASK = (
    "хочу собрать python-CLI для заметок: команды add, list, search, delete. "
    "json-storage, pytest. спроектируй и реализуй с тестами."
)


def _run(args: list[str], timeout: int) -> tuple[int, str]:
    p = subprocess.run(
        CLI + args, cwd=REPO, capture_output=True, text=True, timeout=timeout, check=False
    )
    return p.returncode, (p.stdout + p.stderr).strip()


def _start(base_url: str) -> str | None:
    for _ in range(4):
        rc, out = _run(
            ["start", "notes_cli", "notes_cli_empty", "--base-url", base_url], timeout=120
        )
        rid = out.strip().splitlines()[-1].strip() if out.strip() else ""
        if rid.startswith("notes_cli-"):
            return rid
        time.sleep(5)
    return None


def _verdict(run_id: str) -> dict[str, object]:
    vp = REPO / "docs" / "article" / "probe-runs" / run_id / "verdict.json"
    if not vp.is_file():
        return {}
    data: dict[str, object] = json.loads(vp.read_text())
    return data


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    base_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:1234"
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else REPO / "nightly_results.jsonl"
    out_path.write_text("")

    solved = 0
    crit_pass: dict[str, int] = {}
    done = 0
    for i in range(1, n + 1):
        print(f"[{i}/{n}] start…", flush=True)
        rid = _start(base_url)
        if rid is None:
            print(f"[{i}/{n}] start failed — skip", flush=True)
            continue
        try:
            _run(["step", rid, TASK, "--mode", "plan"], timeout=600)
            _run(["go", rid], timeout=2000)
            _run(["finalize", rid], timeout=600)
        except subprocess.TimeoutExpired:
            print(f"[{i}/{n}] {rid} timed out", flush=True)
        v = _verdict(rid)
        done += 1
        is_solved = bool(v.get("mechanical_solved"))
        solved += int(is_solved)
        crits = v.get("criteria", {})
        if isinstance(crits, dict):
            for k, c in crits.items():
                if isinstance(c, dict) and c.get("passed"):
                    crit_pass[k] = crit_pass.get(k, 0) + 1
        rec = {
            "i": i,
            "run_id": rid,
            "solved": is_solved,
            "pass_score": v.get("pass_score"),
            "pass_max": v.get("pass_max"),
        }
        with out_path.open("a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(
            f"[{i}/{n}] {rid} solved={is_solved} {v.get('pass_score')}/{v.get('pass_max')}",
            flush=True,
        )

    print("=" * 50, flush=True)
    print(f"AGGREGATE: solved {solved}/{done} (attempted {n})", flush=True)
    for k in sorted(crit_pass):
        print(f"  {k:14s}: pass {crit_pass[k]}/{done}", flush=True)


if __name__ == "__main__":
    main()

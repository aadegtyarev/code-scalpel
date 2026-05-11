"""Synthetic bench: full-map (v0.2) vs overview+drilldown (v0.3) on the
SAME patch scenarios, same model, same prompts.

Article chapter 12 promised an honest v0.2 vs v0.3 comparison: the
recalibrated v0.3 LLM bench landed at 27/+5xfail, v0.2 was 30/31, and the
drop looked bad in isolation. The article argues this is calibration
drift (model behaviour changed, asserts didn't move) plus a real
patch-precision regression. The only way to separate the two is to run
the SAME tasks under both context strategies and compare side by side.

What this stand does:

- For each context-sensitive task (six patch shapes lifted from the LLM
  bench), spin up two StepAgent instances against the same temp git
  repo. Both share the same model profile, the same prompt, the same
  config — only the `_user_message` differs:

    * overview mode  — default: send `build_map_overview` (paths + line
                       counts), let the model drill in via map_file /
                       read_file.
    * full-map mode  — monkeypatched: send `build_map` (full eager
                       signatures + docstrings + imports per file)
                       like v0.2 did.

- Per scenario record: applied_ok (apply_edits succeeded), check_ok
  (the same assertion the LLM bench uses), total_tokens
  (prompt+completion across the turn), elapsed_seconds.

- Print a side-by-side table and a summary.

Detection of LM Studio availability is a 2-second probe on /v1/models;
when down, exit 0 with a "skip" message so this is safe to drop into
CI.

This script is read-only against the codebase: the monkeypatch is
local to the script (re-binds `StepAgent._user_message` on an instance
basis), production agent.py is untouched.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import sys
import tempfile
import textwrap
import time
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

# Allow running as `python scripts/bench_full_vs_overview.py` without install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from code_scalpel.agent import StepAgent  # noqa: E402
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile  # noqa: E402
from code_scalpel.llm.adapter import OpenAICompatibleAdapter  # noqa: E402
from code_scalpel.patch.edit_block import apply_edits  # noqa: E402
from code_scalpel.project_map import build_map  # noqa: E402
from code_scalpel.tools.shell import AsyncShellRunner  # noqa: E402

# Same profile shape as test_llm_bench so the comparison stays honest.
_PROFILE = ModelProfile(
    provider="lmstudio",
    model="qwen/qwen2.5-coder-14b",
    temperature=0.1,  # type: ignore[arg-type]  # float shorthand → ModeTemperatures
    seed=42,
)
_CONFIG = AppConfig(
    profiles={"local": _PROFILE},
    agent=AgentConfig(max_files=3, max_file_lines=120),
)


# ── scenarios ────────────────────────────────────────────────────────────────


# Six patch shapes from the LLM bench that are most context-sensitive —
# they're the ones article chapter 12 calls out (the three v0.3 xfails plus
# three matched-difficulty controls that v0.2 also got right).
@dataclass(frozen=True)
class Scenario:
    name: str
    files: dict[str, str]
    prompt: str
    check: Callable[[Path], None]


def _contains(rel: str, *needles: str) -> Callable[[Path], None]:
    def check(root: Path) -> None:
        text = (root / rel).read_text()
        for n in needles:
            if n not in text:
                raise AssertionError(f"{rel!r} missing {n!r}")

    return check


def _lacks(rel: str, *needles: str) -> Callable[[Path], None]:
    def check(root: Path) -> None:
        text = (root / rel).read_text()
        for n in needles:
            if n in text:
                raise AssertionError(f"{rel!r} still contains {n!r}")

    return check


def _all_of(*checks: Callable[[Path], None]) -> Callable[[Path], None]:
    def run(root: Path) -> None:
        for c in checks:
            c(root)

    return run


def _has_annotated_function(rel: str, fname: str) -> Callable[[Path], None]:
    def check(root: Path) -> None:
        tree = ast.parse((root / rel).read_text())
        fn = next(
            (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fname),
            None,
        )
        if fn is None:
            raise AssertionError(f"function {fname} missing from {rel}")
        if fn.returns is None:
            raise AssertionError(f"{fname} has no return annotation")
        if not all(a.annotation is not None for a in fn.args.args):
            raise AssertionError(f"{fname} args missing annotations")

    return check


SCENARIOS: list[Scenario] = [
    Scenario(
        name="rename_function",
        files={
            "calc.py": textwrap.dedent("""\
                def compute(x):
                    return x * 2


                print(compute(5))
                """),
        },
        prompt="Rename the function `compute` to `double` everywhere in calc.py.",
        check=_all_of(
            _contains("calc.py", "def double", "double(5)"),
            _lacks("calc.py", "def compute", "compute(5)"),
        ),
    ),
    Scenario(
        name="add_missing_import",
        files={
            "paths.py": textwrap.dedent("""\
                def home_config():
                    return Path.home() / ".config"
                """),
        },
        prompt="Add the missing `from pathlib import Path` import at the top of paths.py.",
        check=_contains("paths.py", "from pathlib import Path"),
    ),
    Scenario(
        name="remove_unused_import",
        files={
            "uses.py": textwrap.dedent("""\
                import os
                import sys


                def main():
                    print(sys.argv)
                """),
        },
        prompt="Remove the unused `import os` line.",
        check=_all_of(
            _lacks("uses.py", "import os"),
            _contains("uses.py", "import sys"),
        ),
    ),
    Scenario(
        name="add_type_hints",
        files={
            "math_utils.py": textwrap.dedent("""\
                def add(a, b):
                    return a + b


                def subtract(a, b):
                    return a - b
                """),
        },
        prompt="Add type hints to both functions. Use int for parameters and return types.",
        check=_all_of(
            _has_annotated_function("math_utils.py", "add"),
            _has_annotated_function("math_utils.py", "subtract"),
        ),
    ),
    Scenario(
        name="fix_off_by_one",
        files={
            "loop.py": textwrap.dedent("""\
                def first_n(items, n):
                    result = []
                    for i in range(n + 1):
                        result.append(items[i])
                    return result
                """),
        },
        prompt="Fix the off-by-one bug in first_n: the loop range should be range(n), not range(n + 1).",
        check=_all_of(
            _contains("loop.py", "range(n)"),
            _lacks("loop.py", "range(n + 1)", "range(n+1)"),
        ),
    ),
    Scenario(
        name="wrap_in_try_except",
        files={
            "parse.py": textwrap.dedent("""\
                import json


                def load(text):
                    return json.loads(text)
                """),
        },
        prompt="Wrap json.loads in try/except json.JSONDecodeError and return None on failure.",
        check=_contains("parse.py", "try:", "except json.JSONDecodeError", "return None"),
    ),
]


# ── per-run result + table rendering ─────────────────────────────────────────


@dataclass(frozen=True)
class RunResult:
    applied: bool
    checked: bool
    total_tokens: int
    elapsed: float
    note: str  # short reason when something went wrong, "" otherwise


def _format_cell(r: RunResult) -> str:
    if not r.applied:
        mark = "x"
    elif not r.checked:
        mark = "~"  # patch applied but assertion failed
    else:
        mark = "v"
    return f"{mark} {r.total_tokens:>4}t {r.elapsed:>4.1f}s"


def _delta(overview: RunResult, fullmap: RunResult) -> str:
    """One-token verdict: who won this scenario."""
    ok_o = overview.applied and overview.checked
    ok_f = fullmap.applied and fullmap.checked
    if ok_o and ok_f:
        # Both passed — tokens decide.
        if overview.total_tokens < fullmap.total_tokens:
            return f"overview -{fullmap.total_tokens - overview.total_tokens}t"
        if fullmap.total_tokens < overview.total_tokens:
            return f"full-map -{overview.total_tokens - fullmap.total_tokens}t"
        return "tie"
    if ok_f and not ok_o:
        return "full-map wins"
    if ok_o and not ok_f:
        return "overview wins"
    return "both failed"


# ── monkeypatch: force StepAgent to use the v0.2 full eager map ───────────────


def _patch_with_full_map(agent: StepAgent) -> None:
    """Re-bind `_user_message` on this agent instance to use the v0.2
    full map. Production agent.py is untouched.
    """

    def _user_message_full_map(self: StepAgent, task: str) -> str:
        full = build_map(self._cwd, max_files=200, use_cache=False)
        parts = [f"Task: {task}", ""]
        parts.append(
            "Project map — every file with signatures, first-line docstrings "
            "and intra-project imports. Use `read_file` for content when you "
            "need the actual bodies:"
        )
        parts.append(full)
        return "\n".join(parts)

    # Bound method assignment via MethodType, mirroring how a subclass would
    # override. We intentionally don't touch StepAgent.__class__ — the
    # patch must stay isolated to this one instance per run.
    agent._user_message = types.MethodType(_user_message_full_map, agent)  # type: ignore[method-assign]


# ── runner ───────────────────────────────────────────────────────────────────


async def _setup_repo(scenario: Scenario) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix=f"bench-{scenario.name}-"))
    runner = AsyncShellRunner()
    await runner.run(["git", "init", "-q"], cwd=str(tmpdir))
    await runner.run(["git", "config", "user.email", "bench@local"], cwd=str(tmpdir))
    await runner.run(["git", "config", "user.name", "bench"], cwd=str(tmpdir))
    for name, content in scenario.files.items():
        (tmpdir / name).write_text(content)
    await runner.run(["git", "add", "."], cwd=str(tmpdir))
    await runner.run(["git", "commit", "-q", "-m", "init"], cwd=str(tmpdir))
    return tmpdir


def _make_agent(cwd: Path) -> StepAgent:
    profile = _CONFIG.current_profile
    llm = OpenAICompatibleAdapter(
        base_url=f"{profile.provider_base_url()}/v1",
        api_key=profile.api_key(),
        model=profile.model,
    )
    return StepAgent(llm=llm, cwd=cwd, config=_CONFIG)


async def _run_one(scenario: Scenario, *, mode: str) -> RunResult:
    """One scenario × one context-strategy. `mode` is the bench-internal
    label "overview" | "full-map" — not the agent's plan/code mode."""
    cwd = await _setup_repo(scenario)
    agent = _make_agent(cwd)
    if mode == "full-map":
        _patch_with_full_map(agent)

    t0 = time.perf_counter()
    try:
        result = await agent.ask(scenario.prompt, mode="code")
    except Exception as exc:  # pragma: no cover — protective wrap for the LLM call
        return RunResult(False, False, 0, time.perf_counter() - t0, f"llm-error: {exc}")
    elapsed = time.perf_counter() - t0
    total_tokens = result.response.prompt_tokens + result.response.completion_tokens

    if not result.edits:
        return RunResult(False, False, total_tokens, elapsed, "no edits emitted")

    ok, err = apply_edits(result.edits, cwd)
    if not ok:
        return RunResult(False, False, total_tokens, elapsed, f"apply failed: {err[:60]}")

    try:
        scenario.check(cwd)
    except AssertionError as exc:
        return RunResult(True, False, total_tokens, elapsed, f"check failed: {exc}")
    return RunResult(True, True, total_tokens, elapsed, "")


# ── LM Studio availability probe ─────────────────────────────────────────────


async def _lm_studio_up(timeout: float = 2.0) -> bool:
    """2-second probe on /v1/models. Any non-2xx or network error = down."""
    profile = _CONFIG.current_profile
    url = f"{profile.provider_base_url()}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            return resp.is_success
    except Exception:
        return False


# ── main ─────────────────────────────────────────────────────────────────────


def _print_table(rows: list[tuple[str, RunResult, RunResult]]) -> None:
    header = f"{'scenario':<22} | {'overview':<16} | {'full-map':<16} | delta"
    sep = "-" * len(header)
    print(header)
    print(sep)
    for name, ov, fm in rows:
        print(f"{name:<22} | {_format_cell(ov):<16} | {_format_cell(fm):<16} | {_delta(ov, fm)}")


def _print_summary(rows: list[tuple[str, RunResult, RunResult]]) -> None:
    ov_wins = 0
    fm_wins = 0
    ties = 0
    both_failed = 0
    for _, ov, fm in rows:
        ok_o = ov.applied and ov.checked
        ok_f = fm.applied and fm.checked
        if ok_o and ok_f:
            ties += 1
        elif ok_o:
            ov_wins += 1
        elif ok_f:
            fm_wins += 1
        else:
            both_failed += 1

    ov_tokens = sum(r.total_tokens for _, r, _ in rows)
    fm_tokens = sum(r.total_tokens for _, _, r in rows)
    ov_time = sum(r.elapsed for _, r, _ in rows)
    fm_time = sum(r.elapsed for _, _, r in rows)
    ov_applied = sum(1 for _, r, _ in rows if r.applied)
    fm_applied = sum(1 for _, _, r in rows if r.applied)

    print()
    print(f"Scenarios run: {len(rows)}")
    print(f"  overview-only wins : {ov_wins}")
    print(f"  full-map-only wins : {fm_wins}")
    print(f"  both passed (tie)  : {ties}")
    print(f"  both failed        : {both_failed}")
    print()
    print(f"Total tokens:   overview={ov_tokens:>6}  full-map={fm_tokens:>6}")
    print(f"Total seconds:  overview={ov_time:>6.1f}  full-map={fm_time:>6.1f}")
    print(f"Apply-clean:    overview={ov_applied}/{len(rows)}  full-map={fm_applied}/{len(rows)}")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        help="Run only this scenario name (substring match), useful for iteration.",
    )
    # Empty argv during tests; CLI use falls through to sys.argv defaults.
    args = parser.parse_args(argv if argv is not None else None)

    if not await _lm_studio_up():
        print("LM Studio not up at localhost:1234 — exiting (treated as skip).")
        return 0

    scenarios = SCENARIOS
    if args.only:
        scenarios = [s for s in SCENARIOS if args.only in s.name]
        if not scenarios:
            print(f"No scenarios matched --only={args.only!r}")
            return 1

    rows: list[tuple[str, RunResult, RunResult]] = []
    for sc in scenarios:
        print(f"running {sc.name} (overview) …", flush=True)
        ov = await _run_one(sc, mode="overview")
        print(f"running {sc.name} (full-map) …", flush=True)
        fm = await _run_one(sc, mode="full-map")
        rows.append((sc.name, ov, fm))

    print()
    _print_table(rows)
    _print_summary(rows)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(main()))

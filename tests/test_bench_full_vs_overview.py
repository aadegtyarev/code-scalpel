"""Smoke test for the synthetic v0.2-vs-v0.3 context bench.

The real script hits LM Studio; here we only check that:
  - the module imports without dragging in optional/missing deps,
  - the scenario list is non-empty and well-shaped,
  - the LM-Studio probe returns False (and main() exits 0) when
    nothing is listening on the bench port.

No real LLM is contacted from this test.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import scripts.bench_full_vs_overview as bench


def test_module_imports_clean() -> None:
    # Re-import to make sure top-level execution side effects (sys.path
    # tweak, config construction) don't blow up on a fresh load.
    importlib.reload(bench)


def test_scenarios_are_present_and_well_shaped() -> None:
    assert bench.SCENARIOS, "bench should ship at least one scenario"
    seen: set[str] = set()
    for sc in bench.SCENARIOS:
        assert sc.name and sc.name not in seen, f"duplicate or empty name: {sc.name!r}"
        seen.add(sc.name)
        assert sc.files, f"{sc.name}: no fixture files"
        assert sc.prompt, f"{sc.name}: no prompt"
        # check callable shape — pass a temp path that has the fixture
        # files materialised, so a `(root / rel).read_text()` inside check
        # doesn't blow up the smoke test.
        # We only assert the check is callable here; running it would
        # require the patched file, which we don't have.
        assert callable(sc.check)


def test_run_result_cell_marks_clean_and_failed() -> None:
    ok = bench.RunResult(True, True, 100, 1.0, "")
    apply_only = bench.RunResult(True, False, 100, 1.0, "")
    failed = bench.RunResult(False, False, 0, 1.0, "no edits")
    assert _strip_pad(bench._format_cell(ok)).startswith("v")
    assert _strip_pad(bench._format_cell(apply_only)).startswith("~")
    assert _strip_pad(bench._format_cell(failed)).startswith("x")


def test_delta_picks_winner() -> None:
    ok = bench.RunResult(True, True, 100, 1.0, "")
    cheap = bench.RunResult(True, True, 80, 1.0, "")
    failed = bench.RunResult(False, False, 0, 1.0, "")
    # tokens decide when both pass
    assert "overview" in bench._delta(cheap, ok)
    assert "full-map" in bench._delta(ok, cheap)
    # apply matters when only one side won
    assert bench._delta(ok, failed) == "overview wins"
    assert bench._delta(failed, ok) == "full-map wins"
    assert bench._delta(failed, failed) == "both failed"


def test_main_exits_zero_when_lm_studio_down(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Probe returns False → main() prints the skip message and returns 0
    instead of crashing. Lets the script live in CI safely."""

    async def _down() -> bool:
        return False

    monkeypatch.setattr(bench, "_lm_studio_up", _down)
    # main() is async; drive it with the asyncio mode = auto already set
    # for the rest of the suite by running the coroutine here.
    import asyncio

    rc = asyncio.run(bench.main(argv=[]))
    out = capsys.readouterr().out
    assert rc == 0
    assert "LM Studio not up" in out


def _strip_pad(cell: str) -> str:
    return cell.strip()


def test_script_file_exists() -> None:
    # Defensive — if the file is renamed without updating the import,
    # this is the first thing to fail and points at the rename.
    assert Path(bench.__file__).is_file()

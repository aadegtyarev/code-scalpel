# Execution state — archived (flat-layout-run-smoke)

## Task

`feat/flat-layout-run-smoke` — close the two gaps that kept the acceptance gate +
self-fix loop inert on the canonical scenario: (A) flat-layout run-smoke resolution
(`resolve_pkg → RunTarget(kind, target)`: root package / root entry script /
`[project.scripts]`, declared outranks discovered, ambiguity/absence → raise), and
(B) enforce the runnable CLI at the **last applicable task** (`_last_applicable_index`),
not the last plan task. PM-approved scope A+B.

Plan: `docs/features/flat-layout-run-smoke_plan.md`. Arch:
`.ai-pm/arch/flat-layout-run-smoke_arch.md`.

## Status

COMPLETE — shipped (PR opened + merged by PM authorization). Coding + both review
passes + doc/contract handoff + Step-5.5 measurement all done.
- Pass 1 (pm-plan-checker): approve.
- Pass 2 (code-review on Sonnet + seam on session): 5 findings (CR1 inert config knob,
  CR2 src-as-module, CR3 path-traversal candidate, CR4 docstring, CR5 asymmetric src
  ambiguity) — all fixed in 424f6f0, re-verified clean on Sonnet. Stamp written.
- Doc/contract handoff: architecture (new decision record; enforcement position now
  last-applicable; RunTarget descriptor; closed honest-under-enforcement limitation),
  threat-model (T05/T06/T10 reach update, SC7/SC8 reaffirmed), plan.md §31; run-plan
  contract (position wording, cleared both Out-of-scope reach-gap lines).
- Pipeline green: pytest 1350 passed / 40 skipped (+ tests), ruff + mypy clean
  (except pre-existing tools/files.py:8).

## Step-5.5 measurement (the point of the feature)

notes_cli probe batch N=5, mechanical score /8:
- baseline (main c3a1097): 7, 7, 4, 4, 6 → mean 5.6
- after (feature):         5, 6, 5, 5, 6 → mean 5.4

Score statistically FLAT — but the feature works as designed (run-smoke now RUNS
instead of `skipped (pkg-unresolvable)`; loop reaches more tasks: tasks_completed
~4 vs ~2). The flat score is explained by DOWNSTREAM bugs the feature made VISIBLE,
not by a flaw in the feature:
1. f-string quote-reuse thrashing — model rewrites app.py 4× with the same syntax
   error; retry/debug temperature 0.1 too low to escape the deterministic mistake.
2. spec/deliverable name mismatch — derive expects `python -m notes_cli.cli`, model
   builds `app.py` → exit 127 (unfixable by code edits; self-fix fed a wrong command).
3. (related) whole-file rewrite on lint error reintroduces the bug; no formatter pre-pass.

These three are SETTINGS/HARNESS issues, NOT a qwen14b ceiling (micro-edit bench 96%;
other 14B agents work). Next: deep-research (launched) on how aider/cline/openhands +
qwen guidance configure weak 14B (temperature for retry, edit format, context, syntax
recovery), then a single-variable experiment.

## Follow-ups (backlog candidates surfaced)

- Retry/debug temperature too low (0.1) — bump + jitter so a failed rebuild varies.
- f-string syntax recovery — formatter/ruff --fix pre-pass or targeted "fix this line"
  instead of whole-file rewrite.
- Acceptance spec ↔ actual deliverable name reconciliation (echoes F2: don't feed an
  unfixable command error to self-fix).

## Built/changed

- code_scalpel/skills/python_pkg.py (RunTarget + precedence ladder + reserved-dir
  exclusion + traversal guard + symmetric src ambiguity)
- code_scalpel/skills/python_cli_adapter.py (argv-from-kind; bind threads candidates)
- code_scalpel/skills/base.py, skills/__init__.py (bind script_candidates param)
- code_scalpel/config.py (run_smoke_script_candidates + validator)
- code_scalpel/plan_runner.py (_last_applicable_index → should_run_now)
- code_scalpel/plan_verify.py (re-bind adapter with live config)
- tests/test_python_pkg.py, tests/test_flat_layout_run_smoke.py, tests/test_config.py (new)

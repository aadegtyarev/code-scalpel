# Pass-1 plan-compliance review — acceptance-self-fix-loop

Feature: `acceptance-self-fix-loop` · Branch: `feat/acceptance-self-fix-loop`
Commits reviewed: `271da86`, `6e2d1d0` (diff vs `main`).
Scope: plan-compliance only (Pass 1). Technical code quality is Pass 2 / `code-review`.

## Plan completeness (gate before compliance)

- ✓ "Stack expectations touched" present (Pydantic v2 + asyncio) WITH source URLs.
- ✓ "Interaction scenarios" present (feature is not provably isolated — outer loop over shared build→verify, shell I/O, git HEAD, auto-commit hook).
- ✓ Security-bearing project (`docs/threat-model.md` exists) and the feature touches a `### Security-relevant surfaces` item (runs shell + applies patches autonomously). `docs/threat-model.md` IS listed under "Docs to update" (T05/T06/T10 + SCn). Gate satisfied.
- ✓ Not a hotfix topic. ✓ Provenance line present (PM-selected `бери фичу 3`, not `selected autonomously` — no `source:` token required).
- ✓ Categorical coverage — "trust level" set is fully covered: `skeptic` = no-autofix, `optimist`/`yolo` = autofix (the `auto_confirm` gate), no sibling silently chosen; no-new-trust-level / no-per-level-budget listed Out of scope.

## Plan compliance — scenarios

- ✓ S1 Self-fix recovers a task — `_self_fix_acceptance` (plan_runner.py) → test `test_self_fix_recovers_task` (fail-then-pass → `done`, 2 builds).
- ✓ S2 Budget exhausted → failed — `test_self_fix_budget_exhausted_then_failed` (4 distinct failures → `failed`, exactly 1 initial + 3 rebuilds).
- ✓ S3 (skeptic) No auto-fix — `test_skeptic_no_autofix` (trust gate `auto_confirm`; 1 build only, immediate `failed`).
- ✓ S4 Self-fix off → today's behavior — `test_self_fix_off_restores_immediate_failed` (`acceptance_self_fix=False`; immediate `failed`, no rebuild).
- ✓ S5 Only the last applicable task self-fixed — `test_early_task_never_self_fixed` (not `should_run_now`) + `test_library_never_self_fixed` (not applicable). Both stay `done`, no rebuild, no demotion — no-regression invariant held.
- ✓ S6 Language-agnostic — `test_self_fix_language_agnostic` (non-python `_FakeNodeAdapter`; command `node cli.js run`; asserts no `python`/`-m`/`notes_cli` literal in run-smoke calls OR retry prompt).
- ✓ S7 Anti-loop early stop — `test_identical_run_smoke_output_breaks_early` (byte-identical output → stop after 1 rebuild, well under budget 3 → `failed`). Guard in `_self_fix_acceptance` (`new_signal == last_signal`).

## Plan compliance — failure paths (negative-space tests)

- ✓ F8 Rebuild engine raises mid-self-fix — `test_self_fix_code_with_retry_raises` (`code_with_retry` raises on first rebuild → loop does not crash, task `failed`). Matches `try/except Exception` in `_self_fix_acceptance`.
- ✓ F9 Re-run-smoke errors (timeout/refused/non-zero) — `test_self_fix_run_smoke_timeout_attempt` (initial exit-1 → timeout attempt counts and feeds next → recovers). Failed attempt's output carried forward.

## Plan compliance — interaction scenarios

- ✓ HEAD re-snapshot per attempt — `test_head_resnapshotted_each_self_fix_attempt` (auto_git on; `_git_head_sha` queried fresh per attempt, ≥2 snapshots). Backed by `_build_task` re-snapshotting `head_before` each call.
- ✓ Recovered task committed once — `test_recovered_task_is_committed` (auto-commit-on-done; exactly 1 net commit, HEAD advances once — no double-commit).

## Plan compliance — stack-spec tests

- ✓ Pydantic v2 defaults — `test_self_fix_config_defaults` asserts `AgentConfig().acceptance_self_fix is True` and `== 3`; fields declared on `AgentConfig` BaseModel with literal defaults in `config.py` (no magic numbers in loop). Tests against the real default, not a self-consistent mapping.
- ✓ asyncio / language-agnostic — `test_self_fix_language_agnostic` exercises a real non-python adapter through the production verify/run path; the cited rule (adapter-driven, no language literal) is verified against actual run-smoke calls + prompt content, not a stand-in mapping.

## Test-wiring-parity

- ✓ `test_self_fix_recovers_through_run_plan` drives `StepAgent.run_plan()` end-to-end. Confirmed production path: `run_plan` → `PlanRunner.run` → `_run_task` → `_self_fix_acceptance` (agent.py:1259-1261, plan_runner.py:180). The other tests call `_run_task` directly (same production entry into the self-fix cycle); none hand-rolls the loop.

## Arch "must honor" items 1–10

- ✓ 1 (KD1) Loop in `plan_runner._run_task`/`_self_fix_acceptance`, NOT `verify_task`. `plan_verify.py` only added an inline output return — stays a pure reporter; `test_acceptance_enforcement.py` unaffected (49 acceptance tests pass).
- ✓ 2 (KD2) Failing run-smoke output carried inline on new optional `TaskOutcome.acceptance_output` (default `None`, set by `_verify_acceptance` via `dataclasses.replace`, preserved by `_demote`). Not persisted to STATE.json — no state-schema field added.
- ✓ 3 (KD3) Trust gate = `policy.auto_confirm(trust)` machine check in `_self_fix_acceptance`; skeptic returns the demotion immediately.
- ✓ 4 (KD4) Budget + on/off in `config.py` `AgentConfig` pydantic fields; no magic numbers in the loop.
- ✓ 5 (KD5) Identical-output anti-loop guard present (`new_signal == last_signal` → stop).
- ✓ 6 (KD6) No new task-outcome status — reuses `done → failed`; the new field carries a signal, not a status.
- ✓ 9 (KD9) Language-agnostic — `_self_fix_prompt` assembles from task prompt + run-smoke output only; no language literal in `plan_runner` / self-fix path (verified by non-python adapter test).
- ✓ 10 (KD10) `_run_task` extracted — self-fix cycle in private helpers `_build_task` / `_acceptance_demoted` / `_self_fix_acceptance` / `_self_fix_prompt`; `_run_task` reduced to orchestration. (Exact line counts are a Pass-2 lint concern, not plan-compliance.)
- ✓ 7/8 (KD7/KD8) No new temperature knob (reuses code-mode temp); combined ~9-pass bound documented in plan Interaction-scenarios + KD8.
- — Item 10-arch (post-coding threat-model/SCn handoff) correctly deferred to pm-architect; out of Pass-1 scope.

## Product Contract compliance (`.ai-pm/contracts/run-plan.md`)

User-facing feature; contract read. Must-not-break no-regression invariants all held:
- ✓ Early CLI task NEVER demoted — `test_early_task_never_self_fixed` (`done`, no self-fix).
- ✓ Library / no-applicable-spec NEVER failed — `test_library_never_self_fixed` (`done`, no self-fix).
- ✓ Loop stops after N consecutive failures, partial progress kept — self-fix is bounded (budget) and `_run_task` returns through the unchanged consecutive-failure stop in `PlanRunner.run`; F8 test confirms partial progress preserved.
- ✓ Status taxonomy unchanged — no new status (KD6/S2); the new field is a within-turn signal.
Contract doc updates (new Must-work line, removing Out-of-scope deferral lines 90–92, Acceptance-checks bound) are an orchestrator-at-handoff task per the plan — correctly POST-review, not blocking Pass 1.

## Definition of Done

- [x] All plan scenarios implemented and tested (S1–S7 + F8/F9)
- [x] Interaction scenarios have concurrent/post-condition-state tests (HEAD re-snapshot; recovered-task single commit)
- [x] Stack expectations respected; stack-spec tests pass (pydantic defaults; non-python adapter)
- [x] Product Contract honored; no-regression invariants hold; no silent behavior change (no new status)
- [x] Pipeline green — `pytest` 1298 passed / 40 skipped; `ruff check .` clean; `ruff format --check .` clean. (One `mypy` error at `code_scalpel/tools/files.py:8` is PRE-EXISTING on `main` in a file this diff never touches — not a regression, out of scope.)
- [x] State file updated (`.ai-pm/state/current.md` — feature 3 entry)
- [x] Product Impact Report — contract doc-edit handoff is orchestrator-at-handoff (post-review); coder correctly did not touch docs/contract
- [x] Docs updates listed in plan land at the pm-architect/orchestrator handoff (post-review by design) — coder touched no docs (verified: diff has no `docs/` content changes beyond the plan/arch artifacts)
- [x] Expected artifacts exist — plan, this review, contract (user-facing) all present
- [x] Product-readiness gate resolved — advocate artifact present, verdict `clean`
- [n/a] Validation gate — `software`-kind project
- [x] Failure-inventory negative-space tests present — F8 + F9 each have a dedicated test

**DoD: pass**

## Blocking

None.

## Notes (product)

None. No scope expansion (only the planned files + the one new test file changed; no existing test weakened — all `test_acceptance_enforcement.py` assertions intact). No diff-noise / cosmetic hunks observed. No wire-token introduced into PM-facing contract sections (the config-key grammar lives in the plan's `## Contracts`, not in the contract's `## User value` / `## Out of scope`).

Deferred (correctly, NOT blocking Pass 1): the live `notes_cli` Step-5.5 outcome probe (consistency lever, pre-ship), and the doc/contract handoff (pm-architect: user-journeys/architecture/threat-model/plan.md; orchestrator: run-plan contract) — both explicitly post-review per the plan.

## Verdict

approve

## Code review findings

Pass-2 ran two reviewers on the diff vs `main` (commits `271da86`, `6e2d1d0`):
- **code-review** (built-in skill) on **Sonnet** (`review-diff-model: auto`, independent of the Opus session) — model self-reported `claude-sonnet-4-6`.
- **seam-completeness** 3-item angle on the session model (Opus).
Semgrep pre-check skipped (not installed). No backlog / prior findings to dedup against.

**No blocking findings.** Both reviewers independently confirmed the core is sound: the rebuild budget is provably finite (`range(budget)`, all exit paths enumerated), the trust gate is a real machine check (`policy.auto_confirm(trust)` on the live config, not on LLM output), the anti-loop guard is a correct byte-equality early-stop, async is clean (all I/O awaited), and the new optional `TaskOutcome.acceptance_output` is read symmetrically across every reader + `_demote`/`dataclasses.replace` and is never persisted to STATE.json (matches its docstring contract). Seam check: (a) clean, (b) clean, (c) clean.

Six notes, with orchestrator disposition:

- **F1 — FIX — `_self_fix_prompt` docstring over-claims "adds NO language literal"** (`plan_runner.py:397-403`). Raised by both reviewers. The body interpolates English instructional framing ("The deliverable was built but its acceptance run did not pass…"), yet the docstring + plan KD9 read "NO language literal." KD9's real invariant is *target-programming-language/tool*-agnosticism (no `python`/`-m`/`notes_cli` literal — exactly what `test_self_fix_language_agnostic` enforces); English instructional text is correct per the artifact-English canon. Disposition: tighten the docstring wording to say "no *target-language/tool* literal" so the doc matches the (correct) code and the enforced test invariant.

- **F6 — FIX — config budget comment understates the real ceiling** (`config.py:142-146`). The comment says "~9 build passes," which silently assumes `max_debug_attempts ≈ 2`. The true worst case is `acceptance_self_fix_max_attempts × (max_debug_attempts + 1) + 1`, and both factors are independently user-configurable. Disposition: rewrite the comment to state the compound bound rather than the soft "~9".

- **F2 — ACCEPT (with context) — a `refused` initial verdict (policy/sandbox block) triggers one wasteful rebuild** (`plan_runner.py` / `plan_verify.py`). A `refused: sandbox=on requires bwrap…` is infra, not a code defect, so the rebuild is futile — but the anti-loop guard caps the waste at exactly one `code_with_retry` (the refused output is deterministic → identical → early stop). Suppressing self-fix on `refused` would also **contradict the approved plan F9**, which intentionally feeds `timeout/refused/non-zero` forward. Bounded + plan-aligned → accept. Backlog candidate if the one-pass waste is later judged worth a dedicated `refused`-skip.

- **F3 — ACCEPT (with context) — `_last_step_result` is mutable instance state** (`plan_runner.py:88-94`). Communicated across `_build_task` → `_run_task`/`_self_fix_acceptance` via `self`, guarded by `assert`. Safe in practice: `PlanRunner` is constructed fresh per `run_plan`, asyncio is single-threaded, and every read is preceded by a `_build_task` that sets it. The `-O` assert-strip risk is theoretical (no read path lacks a preceding set). Backlog candidate: a clean return-value refactor (return `StepResult` directly) — deferred to avoid churning the freshly-extracted KD10 helpers.

- **F4 — ACCEPT (out of scope) — first build-pass `code_with_retry` raise is uncaught at the `run_plan` boundary** (`plan_runner.py:280` / `agent.py:1261`). **Pre-existing on `main`** — the first build was never wrapped; this diff only makes the asymmetry visible (retries are now resilient via the new `try/except`, covered by F8 `test_self_fix_code_with_retry_raises`). Outside this feature's per-diff scope. Backlog candidate: wrap the first build pass too.

- **F5 — ACCEPT (with context) — byte-exact anti-loop guard can be defeated by volatile run-smoke output** (`plan_runner.py:383-386`). If the deliverable's output embeds timestamps/PIDs/abs-paths, two functionally-identical failures won't be byte-equal and the early-stop won't trip. But the **budget cap (≤3) is the real guaranteed bound** — the early-stop is a best-effort optimization that degrades safely to "exhaust budget," never to a runaway. Backlog candidate: normalize/hash on a stabilized projection (`_failure_reason` class + path-scrubbed body).

### Fixes directed to pm-coder
F1, F6 (doc/comment accuracy in code, no behavior change). F2–F5 recorded as accept-with-context above; no code change. After F1/F6 land, re-verify and stamp.

## Code review: 2026-06-07 — passed

Reviewers: code-review (built-in) on Sonnet + seam-completeness on the session model. No blocking findings. F1/F6 fixed in `8263aed` (doc/comment accuracy, no behavior change) — re-verified clean. F2–F5 recorded as accept-with-context (all bounded/safe; backlog candidates). Pipeline green: pytest 1298 passed / 40 skipped, ruff check + format clean, mypy clean (one pre-existing `tools/files.py:8` error untouched by this diff).

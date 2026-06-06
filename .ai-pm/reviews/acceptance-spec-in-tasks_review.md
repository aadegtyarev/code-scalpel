# acceptance-spec-in-tasks — review

<!-- Pass-1 plan-compliance will be prepended by pm-plan-checker after the doc handoff. -->

## Plan compliance (Pass 1 — pm-plan-checker, 2026-06-06)

Verdict against the post-review plan (`docs/features/acceptance-spec-in-tasks_plan.md`).

- ✓ Scenario 1 (declared/applicable spec enforces — demote on fail) — `plan_verify.py:167` (`if applicable and not ok`); tests `test_enforce_on_derived_applicable_spec`, `test_enforce_on_derived_applicable_spec`/`test_expected_observable_enforced_on_applicable`.
- ✓ Scenario 2 (no-declared → derive args-only, write back, enforce if applicable) — `plan_loading._derive_acceptance` + `_derive_specs_for_tasks`; tests `test_enforce_on_derived_applicable_spec`, `test_derived_spec_written_back_not_rederived`.
- ✓ Scenario 3 (not-applicable / floor-only → observational, NOT demoted — load-bearing no-regression) — gate at `plan_verify.py:167`; floor `applicable=False` lock at `python_cli_adapter.py:191-201`; tests `test_observational_when_derivation_not_applicable` (real library shape, src-layout no `__main__`), `test_floor_only_is_observational`.
- ✓ Scenario 4 (write-back, deterministic next run) — `_persist_derived_tasks` writes TASKS.json + re-renders sentinel; tests `test_derived_spec_written_back_not_rederived`, `test_derived_spec_resumes_from_plan`.
- ✓ Scenario 5 (args-only, adapter-built argv, no free-form shell) — narrow pass returns `{applicable,args,expected}` (`agent.py` `_DERIVE_ACCEPTANCE_SCHEMA` + `derive_acceptance_args`); adapter builds argv via `run_smoke`; `shlex.join(shlex.split(...))` at `plan_verify.py:256`; tests `test_derived_command_is_args_only_adapter_built`, `test_acceptance_command_argv_no_shell`.
- ✓ Scenario 6 (run-loop language-agnostic) — verify path reads only `spec.applicable`/`spec.command`, no language string; test `test_run_loop_enforces_through_a_nonpython_adapter` (fake non-python adapter, demotes through same path).
- ✓ Scenario 7 (non-empty `expected` must appear) — `plan_verify.py:272-273`; test `test_expected_observable_enforced_on_applicable`.
- ✓ Scenario 8 (notes_cli 3/3 via derived path) — manual outcome probe (Step 5.5), not a unit test (per plan); probe-run artifacts present under `docs/article/probe-runs/notes_cli*`.
- ✓ Failure path 9 (derivation fails → floor, observational, no crash) — `_derive_specs_for_tasks` leaves task untouched on `None`; test `test_derivation_failure_falls_back_observational`.
- ✓ Failure path 10 (write-back fails → in-memory, old sentinel, no corruption) — `_persist_derived_tasks` swallows OSError, `_derive_acceptance` returns old hash; test `test_writeback_failure_uses_inmemory_and_logs`.
- ✓ Failure path 11 (applicable timeout/non-zero → demote with reason; timeout from config) — `_failure_reason` + `shell_exec_timeout` from config (no magic number); covered via `test_enforce_on_derived_applicable_spec` / `_failure_reason` mapping.
- ✓ Failure path 12 (pkg-unresolvable: applicable demotes, not-applicable observes) — `plan_verify.py:231-243` + `_adapter_applicable`; test `test_applicable_pkg_unresolvable_demotes_vs_notapplicable_observes`, `test_pkg_unresolvable_recovers_source_for_derived`.

**KD verification (spawn asks):**
- ✓ KD2 — demotion gated strictly on `spec.applicable`; floor never sets applicable (`_floor_spec` hard-codes `applicable=False`, asserted noop-never-applicable at `plan_verify.py:161`). Library / not-applicable / floor-only is observational.
- ✓ KD2b — prose B is NOT executed as argv: adapter precedence is derived (C) → floor (A) (`acceptance_spec` at `python_cli_adapter.py:125-150`); prose feeds derivation as a hint (`_human_acceptance_hint`); `test_acceptance_spec_precedence` + `test_prose_declared_acceptance_is_never_false_demoted` confirm C→A and no prose-as-argv false-demote.
- ✓ KD3 — args-only json_schema narrow pass; adapter builds argv; stack-spec `test_acceptance_command_argv_no_shell` + `test_derived_command_is_args_only_adapter_built`.
- ✓ KD1 — no language string in the verify path; `test_run_loop_enforces_through_a_nonpython_adapter`.
- ✓ Composition / write-back — `_merge_annotated_skills` preserves typed `Task` fields (data-loss fix); write-back not flagged as `plan_modified`; tests `test_pre_passes_preserve_typed_fields`, `test_annotation_and_derivation_compose`, `test_writeback_not_flagged_as_plan_modified`.

**Interaction scenarios (all have concurrent/post-condition tests):**
- ✓ Write-back not a user mid-run edit — `test_writeback_not_flagged_as_plan_modified`.
- ✓ Both pre-passes compose — `test_annotation_and_derivation_compose`.
- ✓ Resume reads written-back spec — `test_derived_spec_resumes_from_plan`.
- ✓ Runs at yolo on skeptic project — `test_acceptance_runs_at_yolo_on_skeptic_project`.
- ✓ Demotion produces the feature-3 signal cleanly (source recovered on failure path) — `test_pkg_unresolvable_recovers_source_for_derived` (does NOT route back, per scope).

**Stack expectations:** ✓ json_schema structured output (`test_derivation_uses_json_schema_structured_output`); ✓ subprocess argv/no-shell (`test_acceptance_command_argv_no_shell`, cites asyncio-subprocess security URL); ✓ `python -m <pkg>` adapter argv; ✓ bwrap/execute() boundary inherited.

**Product Contract (`run-plan.md`):** ✓ Must work updated (enforces where applicable). ✓ Must not break updated (library no-regression is the load-bearing invariant — matches code). ✓ Built/changed-by entry appended. ✓ Acceptance check = notes_cli N≥3 enforced release gate. No silent behavior change — the observational→enforcing flip is the intended, documented change.

**Stack expectations / Interaction sections present in plan** (security-bearing project; feature touches the command-execution surface): ✓ "Stack expectations touched" with source URLs; ✓ "Interaction scenarios"; ✓ `docs/threat-model.md` in Docs to update (T11 resolved + T12 + SC7).

**Docs to update (all on-branch, commit 1fa6855):** ✓ architecture.md (enforcement decision + SC7 defined `:642-648`); ✓ user-journeys.md (Journey 5 — enforcing-where-applicable, libraries unaffected); ✓ threat-model.md (T11 resolved, T12 added, SC7 defined, Last reviewed bumped); ✓ plan.md (v0.14 ✓); ✓ contract. All describe ENFORCING-WHERE-APPLICABLE, not "done always requires run-smoke" — confirmed.

**Out of scope respected:** ✓ no self-fix route-back (feature 3); ✓ no Node adapter (feature 5); ✓ no free-form model commands (args-only); ✓ no enforcement where no applicable spec.

**Selection-citation backstop:** plan `Source:` cites the parent arch note Fork 2 + PM greenlight (`selected autonomously` not the provenance form used — PM-greenlit named feature); n/a. Advocate `auto`-entry citation check: advocate verdict is `clean` (no `## Resolutions` `auto` entries) — n/a.

## Definition of Done
- [x] All plan scenarios implemented and tested
- [x] Interaction scenarios have concurrent-state tests
- [x] Stack expectations respected; stack-spec tests pass
- [x] Product Contract honored; Acceptance checks pass; no silent behavior change
- [x] Pipeline green (pytest 1278 passed/40 skipped; ruff check + format clean; mypy clean cacheless — the lone `tools/files.py:8` unused-ignore is a pre-existing env-stub artifact on a file NOT touched by this diff, already noted in the Pass-2 trail; not a feature regression)
- [x] State file updated (`.ai-pm/state/current.md`)
- [x] Product Impact Report present (contract touched; Pass-2 trail + advocate cover impact)
- [x] Docs updates landed (commit 1fa6855)
- [x] Expected artifacts exist (plan, this review, contract — feature is user-facing)
- [x] Product-readiness gate resolved (user-facing — advocate `clean`, `.ai-pm/reviews/acceptance-spec-in-tasks_advocate.md`)
- [n/a] Validation gate (software-kind project — code Pass-2 applies, not a documentation validation stamp)
- [x] Failure-inventory negative-space tests present (failure paths 9-12 each have a negative-space test)

**DoD: pass**

## Blocking
None.

## Notes (product)
1. The acceptance derivation fires one LLM pass per acceptance-less task at every `/go` (default `auto_derive_acceptance: true`), and auto-rewrites TASKS.{json,md} with the derived spec. This matches the existing `auto_annotate_plan` precedent and is surfaced via the pre-loop card, but it is a new per-run, model-driven side effect on a weak local model — worth the PM knowing the deliverable's acceptance command is now model-influenced (args-only) and editable in the plan before first run. Why it matters: the user sees (and can edit/reject) the derived acceptance args before they execute, but the default-on behavior means a `/go` now does extra LLM work and rewrites the plan file unprompted.

## Verdict
approve



## Code review findings
Pass-2 technical review (code-review skill, high effort: 7 finder angles → verify). **Security (args-only) verified SOLID** — `shlex.join(shlex.split(...))` neutralizes every metacharacter payload (`add; rm -rf ~`, `$(whoami)`, backticks, `&&`, `|`, `>`, newlines); the verb is always code-owned `run_smoke`; only args are model/human-influenced and tokenized; the tuple→`AcceptanceSpec` migration has no stale consumers. The PM's args-only decision is correctly enforced.

### Blocking (fix before ship)

1. **Composition data-loss: the two pre-passes corrupt the typed plan on disk.** `_annotate_plan`'s *change-path* re-parses its output via `parse_tasks_md` (`plan_loading.py:167`), which drops ALL typed `Task` fields (`goal`/`files`/`acceptance`/`test_command`) — the "finding 7" trap, only fixed on the no-change path in feature 2. The new `_derive_acceptance` then (a) runs `derive_acceptance_args` on those stripped tasks → derives from title alone (empty goal/files → wrong/empty args, persisted as a marker and never re-derived), and (b) `serialize_tasks_json(new_tasks)` writes the emptied `goal`/`files`/`test_command` back to TASKS.json — **permanently destroying the user's typed plan**. Fires when both gates are true (fresh JSON plan, no skills + no acceptance — the common case). **Fix:** the annotation change-path must preserve typed fields (merge derived skills into the typed tasks, not re-parse markdown), and derivation must run on full typed tasks and never persist a field-stripped plan.

2. **Human-declared (B) acceptance breaks prose tasks and is exit-0-only.** `_declared_spec` (`python_cli_adapter.py:161-166`) space-joins ALL human acceptance bullets and routes them through `run_smoke(args)` as argv, AND hardcodes `expected=""`. Human acceptance bullets are PROSE ("the note appears in the list"), not CLI args → the loop runs `python -m <pkg> the note appears in the list`, the CLI errors, the spec is forced `applicable=True`, and the task is **demoted `done→failed` every run**. There is no structured declared-args data shape today (`Task.acceptance` is free-prose `tuple[str]`). **Resolution (orchestrator, autonomous — derivable from the no-regression principle + args-only):** in THIS feature, human-declared prose is NOT executed as argv — it is recorded and may feed the derivation as a hint; enforcement uses the derived (C, args-only) or floor (A) spec. Direct enforcement of a *structured* declared spec is deferred to a follow-up (the prose→args data shape isn't there). The binding requirement: **a task with prose acceptance must never be false-demoted.** notes_cli (no human acceptance) is unaffected — it uses C. Plan/contract updated to reflect B = hint, not direct-enforce, this iteration.

3. **`pkg-unresolvable` path drops `source` and `expected`.** When `acceptance_spec` raises (resolve_pkg / argv-assembly), `plan_verify.py:219` returns `source=None` even for a derived/declared task, and the expected-observable check is skipped. Feature-3's self-fix keys off `source`; losing it on exactly the failure path it most needs is wrong. **Fix:** recover `source` (and applicability) from the task on this path, consistent with the normal path.

### Should-fix (same pass)

4. **A prefix-shaped-but-undecodable marker wedges the task.** A `derived-acceptance:`-prefixed line with malformed JSON decodes to `None` → `_derive_specs_for_tasks` skips re-derivation (acceptance non-empty) AND `_declared_spec` treats it as declared args → enforces garbage forever, no path back to derive/floor. **Fix:** an undecodable marker is treated as absent (re-derive) or floor — never as declared args.
5. **Malformed args quoting mislabeled `pkg-unresolvable`.** `shlex.split` raising on unbalanced quotes in args is caught by the `except ValueError` meant for `resolve_pkg`, so a derived/declared arg-quoting error is reported as `pkg-unresolvable` (wrong cause) and demotes. **Fix:** separate arg-build/shlex errors from resolve_pkg errors; a malformed derived spec should fall back (not demote a healthy package).
6. **Unify the dual-source applicability.** `_task_acceptance_applicable` (`plan_verify.py:253`) re-derives the same precedence rule the adapter encodes in `AcceptanceSpec.applicable`. They agree today but can silently diverge on a future tier change (only when `resolve_pkg` raises — environment-dependent). **Fix:** expose applicability without building the command (e.g. an adapter `acceptance_applicable(task)` that doesn't call `run_smoke`/`resolve_pkg`), so there is ONE source.

### Non-blocking cleanups
7. `derive_acceptance_args` `except (Exception, json.JSONDecodeError)` — the second clause is dead (subclass), and the broad catch silently swallows a *wholesale* derivation outage (LLM down → every task floors → "no enforceable specs" reads as "no CLI here"). Surface a systematic-outage signal; drop the dead clause.
8. The noop-never-demotes invariant is load-bearing but enforced only by the two current return sites, not the gate (`if applicable and not ok`). Document/assert it.
9. Marker = JSON-in-`tuple[str]` smell (vs a typed `Task` field) — acceptable for scope, but every `task.acceptance` consumer is one missed `decode` from leaking `derived-acceptance:{...}` into UI/argv.
10. Derivation = one LLM pass per acceptance-less task (N serial passes at plan startup on a weak local model) — acceptable for scope; note the latency.
11. `auto_derive_acceptance` defaults `True` (LLM call + auto-rewrites TASKS.{json,md} on every `/go`) — consistent with the existing `auto_annotate_plan` precedent; surfaced as a UX note, not a defect.

**Orchestrator decision:** 1–3 block ship; 2 resolved autonomously toward the safe behavior (B = hint, not direct-enforce, this iteration — announced to PM). 4–6 should-fix bundled in; 7–11 cleanups. All routed to `pm-coder`. The notes_cli 3/3 outcome probe (the feature's acceptance criterion) runs at Step 5.5 before ship.

## Code review: 2026-06-06 — passed

All findings closed in fix commit `949611f` (verified):
- **1 (data-loss):** `_merge_annotated_skills` merges LLM skills into the typed tasks tuple — both annotation paths now preserve goal/files/acceptance/test_command; derivation runs on full typed tasks; no field-stripped plan is persisted. (Also fixes the pre-existing annotation change-path bug.)
- **2 (prose B):** human-declared prose is no longer executed as argv — it feeds derivation as a hint; enforcement is derived (args-only) or floor only. No false-demote of prose-acceptance tasks.
- **3 + 6:** single applicability source (`acceptance_applicable`) used by the normal and pkg-unresolvable paths; `source` recovered on failure (feature-3 provenance).
- **4:** undecodable marker re-derives (not treated as declared args). **5:** malformed args → distinct reason (`malformed-args`), not mislabeled `pkg-unresolvable`. **7:** dead JSONDecodeError clause dropped + wholesale-outage surfaced. **8:** noop-never-applicable asserted.

Security args-only invariant preserved; generality (no language string in the run-loop verify path) preserved. Pipeline green: pytest 1278 passed / 40 skipped (the single `test_app.py::test_slash_map_mounts_tool_use_card` failure on the first run was a flaky async-TUI test — green on re-run + passes in isolation + HEAD full suite green); ruff check + format clean; mypy clean cacheless (incl. `tools/files.py:8` — not flagged this run). Both passes clear → ready for doc handoff + outcome probe + ship.

# acceptance-spec-in-tasks — review

<!-- Pass-1 plan-compliance will be prepended by pm-plan-checker after the doc handoff. -->

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

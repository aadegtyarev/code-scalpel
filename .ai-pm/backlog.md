# Backlog

Technical-debt and enhancement items deferred with a recorded rationale. Each
entry names its source, severity (as triaged at acceptance — never re-inflated),
and why it was deferred rather than fixed.

## acceptance-self-fix-loop (Pass-2 review, 2026-06-07)

- **F4 — wrap the first build-pass at the `run_plan` boundary** · note · accepted
  (PM, 2026-06-07). The `try/except` added by this feature makes self-fix
  *retries* resilient to `code_with_retry` raising, but the **first** build pass
  (`plan_runner._build_task` → `code_with_retry`, ~`plan_runner.py:280`,
  reaching `agent.py:1261`) is unguarded — a raise there aborts the whole plan
  run instead of recording a `failed` outcome. **Pre-existing on `main`** (the
  first build was never wrapped); this diff only makes the asymmetry visible.
  Real resilience gap. Fix: wrap the first build pass symmetrically so a
  transport/model raise on the last task degrades to a recorded failure.

- **F5 — normalize the anti-loop signal instead of byte-exact compare** · note ·
  accepted (PM, 2026-06-07). The identical-output early-stop
  (`plan_runner.py:383-386`) compares the full run-smoke output byte-for-byte;
  volatile content (timestamps, PIDs, absolute temp paths) makes two
  functionally-identical failures non-equal, so the early-stop never trips and
  the loop runs the full budget. **Safe today** — the budget cap (≤3) is the
  real guaranteed bound; the early-stop is only an optimization. Fix: compare a
  stabilized projection (`_failure_reason` class + path/timestamp-scrubbed body)
  or document the guard as best-effort.

- **F2 — skip self-fix on a `refused` verdict** · note · accepted (PM,
  2026-06-07). A `refused` initial acceptance verdict (no `bwrap` / policy
  block) is infra, not a code defect, so the rebuild is futile — bounded to
  exactly one wasted `code_with_retry` by the anti-loop guard. Deferred because
  suppressing self-fix on `refused` would **contradict the approved plan F9**,
  which intentionally feeds `timeout/refused/non-zero` forward; resolving the
  tension needs a deliberate plan revision, not a quiet code change. Very minor
  (one wasted local LLM pass). Fix (if pursued): distinguish an
  infra-`refused` (sandbox/policy) from a deliverable-`refused` and skip
  self-fix only for the former, updating F9 accordingly.

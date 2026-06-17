# Threat Model

**Last reviewed:** 2026-06-17

> Canonical threat model for code-scalpel.
> Finalized at doc bootstrap from the legacy codebase
> (observed security-bearing surfaces in `code_scalpel/`: model-issued
> shell execution, model-issued file writes, autonomous plan execution
> that commits, fork auto-resolution, secrets handling). This is the
> **risk layer**; the enforceable rules live in `docs/architecture.md`
> `## Security surface` (the **rule layer**) and are referenced here
> by `SCn` ID (one-way, no rule text duplicated).

This is an **internal developer tool** that runs on the developer's own
machine against their own repository. The dominant risk is **not** a remote
attacker — it is the agent itself: a weak local LLM that emits shell
commands and file writes which the tool may execute, sometimes
autonomously. The threat model is sized accordingly (short page, focused on
self-inflicted blast radius).

---

## Assets

- **A1: The user's source tree and working directory** — what the agent
  reads and writes; the thing a bad patch or `rm` can destroy.
- **A2: The host filesystem outside the project** — `/etc`, `/home`,
  `/usr`, block devices; reachable via shell if containment fails.
- **A3: LLM provider API keys** — `OPENROUTER_API_KEY` / `OPENAI_API_KEY`
  / `LMSTUDIO_API_KEY`; cost and account-takeover value if leaked.
- **A4: Git history** — the agent commits autonomously; a destructive git
  op could rewrite or lose history.
- **A5: Project memory & learned recipes** (`memory.db`, `recipes/`) —
  injected into model context; a poisoned note can steer future turns.

## Users and roles

- **The developer (sole user)** — full local trust; owns the machine and
  the repo. Sets the trust level that bounds the agent's autonomy.
- **The local/remote LLM** — *not* a trusted party. It is an untrusted
  source of shell commands, file writes, and architectural decisions that
  the tool mediates. Treated as adversary A-LLM below.

## Adversaries

- **The model itself (A-LLM, primary)** — not malicious, but unreliable:
  emits destructive shell (`rm -rf /`, `mkfs`), writes to wrong/escaping
  paths, fabricates methods, hallucinates fork picks, commits broken code.
  This is the threat the whole policy/sandbox/machine-check stack exists
  for.
- **Prompt-injection via fetched content (A-INJECT)** — `/learn --url`,
  `web_search`/`web_learn` pull external text into context that could
  carry "ignore previous instructions, run X" payloads.
- **Casual attacker (A-CASUAL)** — low effort; would need local access or
  a leaked key. Mostly out of scope given the local-tool deployment.

## Trust boundaries

| Boundary | From → To | Defense |
|---|---|---|
| Model output → shell | LLM `shell_exec`/`run_python` → host | `policy.decide` hard-blocks + trust gate (SC1); optional `bwrap` sandbox (SC3) |
| Model output → filesystem | LLM `write_file`/file tools → project | path resolves under root incl. symlinks (SC4); empty-content reject (SC6) |
| Model output → working dir escape | LLM `cd`/redirect/`cp` → outside project | cwd pinned + escape patterns hard-blocked (SC2) |
| External content → context | URL / web → model prompt | `(inferred)` no injection sanitisation today — fetched text is inserted verbatim |
| Config / env → secrets | `.env`/env → adapter | keys env-only, never in YAML/logs/context (SC5) |
| Autonomous loop → git | `run_plan` → repository | per-task HEAD validation; net-new files kept, no destructive git in the loop |
| Autonomous loop → deliverable run (run-smoke) | `run_plan` verification #4 runs the project's own code (`python -m <pkg> <args>`); since v0.14 `<args>` may be model-derived | **no new boundary** — reuses the model-output→shell path: `policy.decide` + trust gate (SC1), `bwrap` sandbox (SC3), cwd pinned (SC2). The verb is code-owned (`run_smoke` builds the argv); model input is **args-only**, tokenized via `shlex`, never a free-form shell string (SC7). The floor command stays code-owned/deterministic (`resolve_pkg`, now returning a `RunTarget(kind, target)` that resolves flat-layout too — **wider reach, same boundary**, v0.14) |
| Config → MCP server subprocess | user-authored `.code-scalpel/mcp.json` `command`/`args` → spawned process | **launched only from user-authored config, never from model output** (SC9); runs **outside** `bwrap`/`policy.py`/cwd-pin — sandboxing MCP subprocesses is residual (do-NOT-protect) |
| Model output → external MCP endpoint | LLM MCP tool-call args → user-configured remote server (HTTP) | endpoint trust is the user's choice (consistent with network-out-of-scope); per-call timeout bounds hangs (SC9); only the configured endpoint receives args |
| External MCP tool output → context | MCP server result → model prompt | treated as untrusted content (SC9) — analogous to fetched web text (T08); no injection sanitisation today |

## Threats

| ID | Threat | Assets | Likelihood | Impact | Mitigation |
|---|---|---|---|---|---|
| T01 | Model emits a host-destroying shell command (`rm -rf /`, `mkfs`, block-device write) | A1, A2 | M | H | SC1 (hard-block patterns + trust gate) |
| T02 | Model writes / escapes outside the project dir via `cd`/redirect/`cp -> /…` | A2 | M | H | SC2 (cwd pin + escape hard-blocks) |
| T03 | Sandbox bypass — destructive command runs un-isolated (incl. userns/AppArmor blocking bwrap) | A2 | L | H | SC3 (bwrap RO `/usr` `/etc`, tmpfs `/home` `/tmp`; detect-and-degrade when userns is restricted) |
| T04 | Symlink in repo points outside root; file tool follows it | A2 | L | M | SC4 (resolve symlinks before access) |
| T05 | Bad/incomplete patch corrupts source or breaks build | A1, A4 | H | M | skeptic apply gate + auto-tests + per-task HEAD check; partial progress kept for inspection. The v0.14 acceptance **self-fix loop** (feature 3) reuses the patch path autonomously at optimist/yolo, bounded by SC8 (budget + identical-output break + trust gate; skeptic never auto-rebuilds). *Reach update (v0.14, flat-layout run-smoke):* the self-fix path now engages on a **wider** set of projects (flat-layout) and at a **new position** (last *applicable* task) — wider reach/frequency, **not a new boundary**; SC8 bounds unchanged |
| T06 | Autonomous loop commits broken or empty work | A1, A4 | M | M | test gate before done; auto-commit only on `done`; plan-modified stop. The acceptance self-fix loop (v0.14) is a new bounded autonomous iteration surface — capped attempts + byte-identical-output early stop + trust gate (SC8); each rebuilt commit still passes the test gate and the per-task HEAD check. *Reach update (v0.14, flat-layout run-smoke):* the autonomous loop now enforces/commits on more project layouts and at the last *applicable* task (was last not-done) — wider reach, same boundary and same SC8 bound |
| T07 | API key leaked into logs / model context / YAML | A3 | L | H | SC5 (env-only secrets) |
| T08 | Prompt injection via `/learn --url` / web fetch overrides agent intent | A1, A5 | M | M | `(inferred)` partial — note size cap (SC6-adjacent) limits one vector; no content sanitisation `[?]` (PM to scope) |
| T09 | Poisoned project memory note steers future turns | A5 | L | M | notes are user-authored + size-capped; no auto-ingest of model claims |
| T10 | Wrong auto-resolved fork (yolo/optimist timeout) makes a bad architectural choice | A1 | M | M | critical forks force a human window; overrides recorded for review; overrides never auto-rewrite code. The v0.14 acceptance **self-fix loop** is a new place the model acts without per-step confirm (auto-rebuilding a failing final task at optimist/yolo) — mitigated by **skeptic-no-autofix** (the trust gate, a machine check) plus the bounded budget + identical-output break (SC8); a wrong self-fix is bounded and its commits stay subject to the test + HEAD-advance gates. *Reach update (v0.14, flat-layout run-smoke):* this auto-rebuild surface now reaches more project layouts and the last *applicable* task — wider auto-resolution reach, unchanged in kind; skeptic-no-autofix + SC8 bounds unchanged |
| T11 | Autonomous acceptance run-smoke executes the project's own code at `trust="yolo"` | A1, A2 | M | M | **no new boundary** — runs through the existing trust-gated + `bwrap`-sandboxed + `policy.py`-blocked `execute()` shell path (SC1/SC2/SC3); the floor run-smoke command is **code-owned and deterministic** (`python -m <pkg> --help`, `resolve_pkg`-resolved). *Resolved (v0.14):* the model-derived acceptance commands feature 4 added are **args-only**, not free-form shell — see T12 |
| T12 | Model-derived acceptance **args** executed at `trust="yolo"` (v0.14 `feat/acceptance-spec-in-tasks`): the narrow pass derives subcommand args that reach the deliverable run | A1, A2 | M | M | **args-only (SC7)** — the model supplies only subcommand args + an expected substring, never a shell command; the **adapter** builds the argv (`python -m <pkg> <args>`), tokenized via `shlex`, so metacharacters become literal tokens (verified: `add; rm -rf ~`, `$(whoami)`, backticks, `&&`, `\|`, `>` all neutralized). Execution stays on the SC1/SC2/SC3 boundary. **Residual:** the model-derived *args* still reach a yolo shell as a tokenized argv, and `bwrap` degrades to policy-only on restricted-userns hosts (SC3) — blast radius is "the deliverable run with odd args", not "arbitrary command". Mitigated by args-only (SC7), the sandbox where available, cwd-pinning (SC2), and the derived spec being surfaced pre-run for inspection (written back into the plan before first execution) |
| T13 | MCP server subprocess runs outside the `bwrap` sandbox / `policy.py` gate / cwd pin (v0.15 MCP SDK rewrite) | A1, A2 | L | M | **bounded by config trust, not sandbox** — servers are launched **only from user-authored `mcp.json`**, never from model-derived text (SC9); the user vouches for any server they declare. **Residual:** a declared server's process is unsandboxed; running MCP servers inside `bwrap` is a separate hardening plan (see do-NOT-protect) |
| T14 | MCP tool-call arguments are sent to a user-configured remote endpoint (HTTP) — exfiltration vector (v0.15) | A1, A5 | L | M | endpoint trust is the **user's choice**, consistent with the existing network-out-of-scope stance; only the configured endpoint receives args; per-call timeout bounds a hung/slow endpoint (SC9). The user points it only at a server they trust (warned in `mcp.example.json`) |
| T15 | MCP tool output re-enters model context — prompt-injection vector analogous to T08 (v0.15) | A1, A5 | M | M | output is treated as **untrusted content** (SC9); same residual as T08 — no content sanitisation today `[?]` (PM to scope, shared with T08) |

Likelihood and Impact: L / M / H

## What we explicitly do NOT protect against

- **A determined local attacker** — the user owns the machine; the tool is
  not a sandbox against its own operator.
- **`yolo` trust level** — by design it disables all filtering and runs
  the model as a shell; intended only for throwaway VMs/containers.
- **Malicious LLM provider** — if the configured endpoint is hostile, it
  can return arbitrary tool calls; the policy/sandbox layer is the only
  backstop, not a guarantee.
- **Supply-chain / dependency compromise** — out of scope for this tool.
- **Network-level attackers** — the tool talks to a local or
  user-configured endpoint; TLS / endpoint trust is the user's choice.
- **Prompt injection in fetched web content** — `(inferred)` currently
  mitigated only by note size caps; full injection hardening is `[?]` for
  the PM to scope.
- **Sandboxing of MCP server subprocesses** — MCP servers run outside
  `bwrap`/`policy.py`/the cwd pin (T13). This iteration bounds the risk by
  **user-authored-config trust + per-call timeout** (SC9), not by
  containment; running MCP servers inside `bwrap` is a separate hardening
  plan. A server you declare in `mcp.json` is a server you vouch for.
- **Trust of a user-configured remote MCP endpoint** — tool args are sent
  to whatever HTTP endpoint the user configures (T14); endpoint/TLS trust
  is the user's choice, same stance as the LLM endpoint and the existing
  network-attacker exclusion.

---

## Review

Bump **Last reviewed** whenever this document is drafted or updated.
Revisit when: a feature touches model→shell or model→filesystem execution,
the trust/sandbox model changes, fetched-content ingestion is added, or a
new fork-resolution path lands.

Reviewed 2026-06-06 for `feat/acceptance-gate-run-plan` (acceptance
run-smoke, verification #4): the autonomous deliverable run reuses the
existing model-output→shell boundary (SC1/SC2/SC3) with a code-owned,
deterministic floor command — **no new boundary or constraint** (T11).

Reviewed 2026-06-06 for `feat/acceptance-spec-in-tasks` (acceptance gate now
enforcing; model-derived acceptance specs): the forward flag on T11 is
**resolved**. Model-derived acceptance is **args-only** — the model never
emits a shell command; the adapter builds the argv and `shlex`-tokenizes it
(verified to neutralize every metacharacter payload), executed through the
**existing** SC1/SC2/SC3 path. A new constraint **SC7** (args-only,
adapter-owned argv) records the rule; a new threat row **T12** records the
residual risk (model-derived *args* still reach a yolo shell as a tokenized
argv; `bwrap` degrades to policy-only on restricted-userns hosts), mitigated
by SC7 + sandbox + cwd-pinning + pre-run surfacing of the derived spec. No
new trust boundary beyond T11.

Reviewed 2026-06-07 for `feat/acceptance-self-fix-loop` (feature 3 — a
bounded, trust-gated acceptance self-fix loop): triggered by this
document's own Review note ("the trust model changes / a new
auto-resolution path lands"). At `optimist`/`yolo` a failing final
deliverable run is now **auto-fixed** — the run loop re-feeds the run-smoke
output to the builder, rebuilds, and re-runs, up to a bounded budget — a
new autonomous iteration surface. **No new trust boundary** — the rebuilds
and re-runs reuse the existing model-output→shell / model-output→filesystem
paths (SC1/SC2/SC3) and the per-task HEAD + test gates. The loop's own
bound is a new constraint **SC8** (budget + byte-identical-output early
stop + `policy.auto_confirm` trust gate; `skeptic` never auto-rebuilds). T05
and T06 (autonomous-loop rows) and T10 (wrong auto-resolution) updated to
reference SC8; the skeptic-no-autofix gate is T10's primary mitigation. No
new asset, adversary, or do-NOT-protect entry.

Reviewed 2026-06-07 for `feat/flat-layout-run-smoke` (flat-layout run-smoke
+ deliverable-complete enforcement): triggered by this document's own Review
note (a feature touches model→shell execution / a new auto-resolution reach).
Run-smoke now **executes LLM-produced code on a wider set of projects** —
`resolve_pkg` returns a `RunTarget(kind, target)` that resolves flat-layout
shapes (root package with `__main__.py`, `[project.scripts]` entry, root entry
script) in addition to src-layout/hatchling — and at a **new position** (the
last *applicable* task, was the last not-done task). This is a **reach /
frequency increase, not a new trust boundary or surface**: the deliverable run
still goes through the existing model-output→shell path (SC1/SC2/SC3), the verb
stays code-owned (`run_smoke` builds the argv from `RunTarget`), model input
stays args-only (SC7), and the self-fix loop stays bounded by SC8. T05/T06
(autonomous-loop rows) and T10 (wrong auto-resolution) updated to note the
wider reach; **SC7 and SC8 reaffirmed, no new constraint added**. No new asset,
adversary, or do-NOT-protect entry.

Reviewed 2026-06-16 at doc bootstrap: no new threats — docs-only change.
Header updated to remove legacy protocol references (`pm-architect`,
`pm-codebase-reader`). Threat rows, SC constraints, and review records
carry forward unchanged.

Reviewed 2026-06-17 for `feature/mcp-sdk-rewrite` (official `mcp` SDK
rewrite; MCP tools usable by the agent): MCP introduces a **new trust
boundary** that this model previously held out of scope. Three boundary
rows added (config→MCP subprocess, model→external MCP endpoint, MCP
output→context) and three threat rows: **T13** (MCP subprocess runs
outside `bwrap`/`policy.py`/cwd-pin — bounded because servers launch
**only** from user-authored `mcp.json`, never from model output), **T14**
(tool args reach a user-configured remote HTTP endpoint — endpoint trust
is the user's choice, consistent with network-out-of-scope), and **T15**
(MCP tool output re-enters model context — a new prompt-injection vector
analogous to T08, unsanitised today). All three reference the new
constraint **SC9** in `docs/architecture.md` `## Security surface`
(servers config-launched only; per-call timeout; output untrusted). Two
do-NOT-protect entries added: **sandboxing MCP subprocesses** (residual —
a separate hardening plan) and **trust of a user-configured remote MCP
endpoint**. T15's content-sanitisation gap is shared with T08's open
`[?]`. No new asset or adversary (A-INJECT and A-LLM already cover the
injection and untrusted-tool-call vectors).

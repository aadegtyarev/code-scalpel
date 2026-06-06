# Threat Model

**Last reviewed:** 2026-06-06

> Canonical threat model for code-scalpel. Owned by `pm-architect`.
> Finalized at legacy adoption from the `pm-codebase-reader` draft
> (observed security-bearing surfaces in `code_scalpel/`: model-issued
> shell execution, model-issued file writes, autonomous plan execution
> that commits, fork auto-resolution, secrets handling). This is the
> **risk layer**; the enforceable rules live in `docs/architecture.md`
> `## Security constraints` (the **rule layer**) and are referenced here
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
| Autonomous loop → deliverable run (run-smoke) | `run_plan` verification #4 runs the project's own code (`python -m <pkg> <args>`); since v0.14 `<args>` may be model-derived | **no new boundary** — reuses the model-output→shell path: `policy.decide` + trust gate (SC1), `bwrap` sandbox (SC3), cwd pinned (SC2). The verb is code-owned (`run_smoke` builds the argv); model input is **args-only**, tokenized via `shlex`, never a free-form shell string (SC7). The floor command stays code-owned/deterministic (`resolve_pkg`) |

## Threats

| ID | Threat | Assets | Likelihood | Impact | Mitigation |
|---|---|---|---|---|---|
| T01 | Model emits a host-destroying shell command (`rm -rf /`, `mkfs`, block-device write) | A1, A2 | M | H | SC1 (hard-block patterns + trust gate) |
| T02 | Model writes / escapes outside the project dir via `cd`/redirect/`cp -> /…` | A2 | M | H | SC2 (cwd pin + escape hard-blocks) |
| T03 | Sandbox bypass — destructive command runs un-isolated (incl. userns/AppArmor blocking bwrap) | A2 | L | H | SC3 (bwrap RO `/usr` `/etc`, tmpfs `/home` `/tmp`; detect-and-degrade when userns is restricted) |
| T04 | Symlink in repo points outside root; file tool follows it | A2 | L | M | SC4 (resolve symlinks before access) |
| T05 | Bad/incomplete patch corrupts source or breaks build | A1, A4 | H | M | skeptic apply gate + auto-tests + per-task HEAD check; partial progress kept for inspection |
| T06 | Autonomous loop commits broken or empty work | A1, A4 | M | M | test gate before done; auto-commit only on `done`; plan-modified stop |
| T07 | API key leaked into logs / model context / YAML | A3 | L | H | SC5 (env-only secrets) |
| T08 | Prompt injection via `/learn --url` / web fetch overrides agent intent | A1, A5 | M | M | `(inferred)` partial — note size cap (SC6-adjacent) limits one vector; no content sanitisation `[?]` (PM to scope) |
| T09 | Poisoned project memory note steers future turns | A5 | L | M | notes are user-authored + size-capped; no auto-ingest of model claims |
| T10 | Wrong auto-resolved fork (yolo/optimist timeout) makes a bad architectural choice | A1 | M | M | critical forks force a human window; overrides recorded for review; overrides never auto-rewrite code |
| T11 | Autonomous acceptance run-smoke executes the project's own code at `trust="yolo"` | A1, A2 | M | M | **no new boundary** — runs through the existing trust-gated + `bwrap`-sandboxed + `policy.py`-blocked `execute()` shell path (SC1/SC2/SC3); the floor run-smoke command is **code-owned and deterministic** (`python -m <pkg> --help`, `resolve_pkg`-resolved). *Resolved (v0.14):* the model-derived acceptance commands feature 4 added are **args-only**, not free-form shell — see T12 |
| T12 | Model-derived acceptance **args** executed at `trust="yolo"` (v0.14 `feat/acceptance-spec-in-tasks`): the narrow pass derives subcommand args that reach the deliverable run | A1, A2 | M | M | **args-only (SC7)** — the model supplies only subcommand args + an expected substring, never a shell command; the **adapter** builds the argv (`python -m <pkg> <args>`), tokenized via `shlex`, so metacharacters become literal tokens (verified: `add; rm -rf ~`, `$(whoami)`, backticks, `&&`, `\|`, `>` all neutralized). Execution stays on the SC1/SC2/SC3 boundary. **Residual:** the model-derived *args* still reach a yolo shell as a tokenized argv, and `bwrap` degrades to policy-only on restricted-userns hosts (SC3) — blast radius is "the deliverable run with odd args", not "arbitrary command". Mitigated by args-only (SC7), the sandbox where available, cwd-pinning (SC2), and the derived spec being surfaced pre-run for inspection (written back into the plan before first execution) |

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

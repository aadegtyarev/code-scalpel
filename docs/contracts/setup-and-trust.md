# Product Contract: Setup, model profiles & trust control

## User value

The developer can get from install to a working agent in one guided step
(`code-scalpel init`), switch between named model profiles
(local/fast/smart) without editing config, and dial the agent's autonomy up
or down live with a single trust knob — controlling in one place how much
the agent can do (run shell, apply patches, auto-resolve decisions) without
asking.

## Who uses it

A developer configuring code-scalpel for a project and tuning how much they
trust the model to act unsupervised.

## Must work

- `code-scalpel init` walks through provider / model / sandbox and writes
  `.code-scalpel/config.yaml` + a `.gitignore` entry.
- The model context window is auto-detected from the provider; a named
  profile can be switched at launch or at runtime.
- Trust (Ctrl+L: skeptic → optimist → yolo) changes live and is shown in
  the footer; the next turn uses the new level.
- The same trust knob governs shell confirmation, patch auto-apply, and
  fork resolution.

## Must not break

- API keys are never written to YAML — env/`.env` only.
- Skeptic requires explicit confirmation for shell and patches; hard-block
  commands are refused at skeptic and optimist regardless of approval.
- `init` does not overwrite an existing config without confirmation/force.
- Trust-level semantics and hard-block list — see `docs/architecture.md`
  `## Behavioral contract` and `## Security surface`.

## Acceptance checks

- `cli.py` init tests; `config.py` layered-load + context-autodetect tests.
- `policy.py` tests — trust decisions, hard-block coverage, unknown-level
  coercion to skeptic.
- TUI tests — Ctrl+L trust cycle and footer indicator.

## Out of scope

- Managing the LLM server itself (LM Studio must be running separately).
- Per-feature trust overrides beyond the three named levels.

## Last reviewed

2026-06-06 — verified against tree at doc bootstrap.

## Built/changed by

- (legacy — pre-protocol; v0.1, v0.3, v0.6, v0.7, v0.10)

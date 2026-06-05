# Product-readiness — bootstrap advocate

## Product-readiness gaps

Tier: bootstrap
Checklist: `### Foundational product questions` in `workflow/foundational-questions.md`

1. Discovery — how does a new user find out the product exists? — no recorded answer in product.md, architecture.md, or the product Q&A answers. The inputs record how a new user *installs* and *onboards* (`pip install code-scalpel` / GitHub release binary + `.deb`; `code-scalpel init` and Journey 1), which are post-discovery steps, but no discovery channel (how someone first learns the product exists) is recorded.
4. Recovery & key-loss — what happens when a user loses access, a key, or a device? — no recorded answer in product.md, architecture.md, or the product Q&A answers. The inputs record where API keys live (env / `.env` only; SC5) and session/crash recovery (Journey 9, `STATE.json`), but nothing records what happens when the user loses a key, a device, or access.

## Verdict

gaps: 2

## Resolutions

1. Discovery — **answered.** Channel is open-source distribution: the GitHub repository and PyPI (`pip install code-scalpel`), plus the technical article (`docs/article_draft.md`) about how the system was designed as the primary audience-attraction channel. Landed in `docs/product.md`.
4. Recovery & key-loss — **answered.** code-scalpel is a local tool with nothing server-side to recover: API keys (only when a remote endpoint like OpenRouter is used) live solely in the user's `.env`; local LM Studio needs no key; there is no secret store or account. Losing the device means restoring the repo from git like any local tool; access recovery is not the product's responsibility. Landed in `docs/architecture.md` (Security constraints).

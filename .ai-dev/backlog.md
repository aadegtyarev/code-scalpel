# Backlog

## MCP frozen-import smoke in CI
**Priority:** medium
The release binary bundles `mcp` (spike-verified recipe in `release.yml`), but
the CI smoke `./dist/code-scalpel --version` returns before the TUI / MCP import
chain loads, so it does **not** actually prove `mcp` got bundled. A broken
`--collect-*` set would ship undetected.
- Add a hidden `code-scalpel --selfcheck` (or `--version` path) that imports
  `code_scalpel.mcp_client` so the frozen binary exercises the mcp +
  pydantic_core + jsonschema_specifications bundle.
- Wire it into `release.yml` after the binary build.

## Prompt-injection sanitization for untrusted tool output
**Priority:** medium (product decision — threat-model `[?]`)
MCP tool output (T15) and fetched web/`/learn` content (T08) re-enter the model
context unsanitized. Threat model records this as an open `[?]` for scoping.
- Decide the policy: strip/escape "ignore previous instructions"-style
  payloads, wrap untrusted output in a delimiter the model is told not to obey,
  size-cap, or accept-as-is with a documented residual.
- Applies uniformly to MCP results, web fetch, and recipe ingestion.

## MCP resources & prompts
**Priority:** low
v0.15 MCP covers tools only. Resources (server-provided files/data) and prompts
(server-provided templates) are deferred — each needs a UX decision on where it
attaches in the TUI / context. Own plan when picked up.

## MCP server sandboxing
**Priority:** low (hardening)
stdio MCP servers run as raw subprocesses outside `bwrap` / `policy.py` / the
cwd pin (threat-model residual; bounded today by user-authored-config trust +
per-call/connect timeouts). Running them inside the sandbox is a separate
hardening plan.

## Browser automation (Playwright) — verify end-to-end
**Priority:** low
Playwright is the documented MCP example (`mcp.example.json`, stdio). The path
now works through the official SDK client; do a real end-to-end run
(navigate/snapshot/click/type/screenshot) against `@playwright/mcp` and capture
it as a user journey / smoke once exercised.

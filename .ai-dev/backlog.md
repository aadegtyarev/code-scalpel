# Backlog

## Source-aware recipe-injection wrapping (`/learn --url` vector)
**Priority:** medium (follow-up to v0.16 untrusted-content framing)
v0.16 frames the two direct-to-model external vectors (MCP tool output,
web-search results) as untrusted (SC10). The remaining open residual is the
`/learn --url` → recipe path (threat T08): fetched page content is written
verbatim into a recipe file and reaches the model later via recipe injection.
- Wrap recipe **bodies** at injection time, but only for `source: url`-derived
  recipes — hand-written recipes must stay un-framed (not treated as untrusted).
- Needs a `source` marker in recipe frontmatter to distinguish the two.
- Closes the T08 residual recorded in `docs/threat-model.md`.

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

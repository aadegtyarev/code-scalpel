from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from code_scalpel.config import AppConfig
from code_scalpel.context_compress import (
    compress_tool_message,
    should_compress,
    summarize_with_llm,
)

if TYPE_CHECKING:
    from code_scalpel.memory import MemoryStore
from code_scalpel.llm.adapter import ChatResponse, LLMAdapter, NativeToolCall
from code_scalpel.patch.edit_block import Edit, apply_edits, extract_edits
from code_scalpel.plan import Task, parse_tasks_md, serialize_tasks
from code_scalpel.tools.agent_tools import (
    SHELL_EXEC_SCHEMA,
    TOOL_SCHEMAS,
    ConfirmShellExec,
    ToolCall,
    ToolResult,
    execute,
)
from code_scalpel.tools.shell import ShellRunner

_MAX_TOOL_ROUNDS = 6

# Retry prompts for code_with_retry. We feed the failure verbatim — weak local
# models reliably benefit from a short, blame-free framing of WHAT broke.
_APPLY_FAILED_PROMPT = (
    "Your previous SEARCH/REPLACE patch did not apply cleanly. The applier "
    "reported:\n\n{error}\n\nProduce a corrected patch. Re-read the target "
    "file first if you're not sure the SEARCH text matches character-for-"
    "character."
)
_TESTS_FAILED_PROMPT = (
    "Your previous patch was applied, but the test suite is now red. Pytest "
    "output:\n\n{output}\n\nProduce a follow-up patch that fixes the failing "
    "test(s). Don't revert the original change unless that's truly the only "
    "way forward."
)
_MISSING_FILES_PROMPT = (
    "The following file(s) do not exist yet: {paths}\n\n"
    "Create each one using a SEARCH/REPLACE block with an **empty SEARCH section** "
    "(that means: no lines between <<<<<<< SEARCH and =======). Example:\n\n"
    "requirements.txt\n"
    "```\n"
    "<<<<<<< SEARCH\n"
    "=======\n"
    "requests\n"
    "prettytable\n"
    ">>>>>>> REPLACE\n"
    "```\n\n"
    "Proceed with the task now."
)

_NEEDS_TESTS_PROMPT = (
    "Your previous patch applied cleanly and the existing tests pass, but it "
    "changed production code without touching any test file. Produce a "
    "follow-up patch that adds a test exercising the new behaviour. Put it "
    "under `tests/`, name it `test_<feature>.py`, and keep the existing "
    "patch on disk — only add."
)


def _changes_include_tests(edits: list[Edit]) -> bool:
    """True if any edit targets a path that looks like a test file."""
    for edit in edits:
        parts = Path(edit.path).parts
        name = Path(edit.path).name
        if "tests" in parts or name.startswith("test_") or name.endswith("_test.py"):
            return True
    return False


def _changes_include_prod_code(edits: list[Edit]) -> bool:
    """True if any edit touches a non-test `.py` file."""
    for edit in edits:
        if not edit.path.endswith(".py"):
            continue
        parts = Path(edit.path).parts
        name = Path(edit.path).name
        if "tests" in parts or name.startswith("test_") or name.endswith("_test.py"):
            continue
        return True
    return False


_FORCE_ANSWER_MSG: dict[str, Any] = {
    "role": "user",
    "content": (
        "You already called these tools with the same arguments. Stop calling "
        "tools and answer the original question now, using what you have."
    ),
}

# Re-prompt when the model emitted a code block targeting a file it never
# read. Weak local models fabricate bodies from training-data shape and
# we'd silently let through patches/snippets that don't match the actual
# source. The HOOK rejects the reply once, asks the model to ground via
# read_file, then accepts whatever it produces on the second pass.
_READ_BEFORE_SHOW_PROMPT = (
    "You produced a code block targeting `{path}` without first reading "
    "the file. Your patch / shown code may not match the actual source. "
    "Call `read_file({path})` now, then re-emit the corrected output. "
    "Do NOT reproduce the original block from memory."
)

# A fenced python block in a reply that has NO surrounding SEARCH/REPLACE
# markers. The HOOK only fires on such blocks when the user's task names a
# specific project file — otherwise the block is conversational example
# code (e.g. answering "how would I write a list comprehension?") and we
# don't have a target to enforce against.
_BARE_PY_FENCE_RE = re.compile(
    r"^[ \t]*```python\n(?P<body>.*?)\n[ \t]*```",
    re.DOTALL | re.MULTILINE,
)

_SYSTEM_PROMPT = """\
Always reply in the same natural language the user used.

Don't open task replies with a self-introduction — the user knows
which tool they launched. Call the relevant tool first and answer
from its output.

Tone: colleague, not customer. Russian — "ты", not "вы". No
corporate hedging, no apologies, no emojis, no slang. Don't
clarify until you've tried tools — first attempt is `project_map`
/ `grep` / `read_file`, ask only after they've come back empty.

Tools: project_map, read_file, goto_definition, find_references,
grep, retrieve, run_tests. Each tool's description is normative —
follow it.

The user message contains ONLY the task. No project listing is
attached — you have to actively explore the codebase. Don't answer
about project structure or specific symbols without calling tools
first; assumptions about file layout are wrong by default.

When a task doesn't name a specific file, your first move is
`project_map()` (no args) to see what's in the project. Then pick
a candidate and continue with `project_map(path)` / `read_file` /
`grep` / `retrieve`. Asking the user "which file?" before that
first project_map call is the wrong default — try the tool first,
ask only if the listing genuinely doesn't help.

Navigation order:
  1. `project_map()` (no args) — tree of files with line counts.
     First tool when the task names no specific file.
  2. `project_map(path="foo.py")` — drill into ONE file: classes,
     signatures, imports. Use after spotting a candidate.
  3. `read_file(path)` — body when you need to quote or edit.
  4. `goto_definition(name)` — jump to a known symbol.
  5. `find_references(name)` — where is X used?
  6. `retrieve(query, path?)` — fuzzy "what's relevant to X" search.
  7. `grep(pattern)` — broader regex search by text.

Grounding rules — do NOT make things up:
- Before you NAME a class / method / function / attribute, verify
  that exact name appears in `project_map(path)` output for the file.
  If it isn't there, don't use it — grep elsewhere or ask "the
  only things I see in that file are X, Y, Z — which did you mean?".
- A similar-looking name does NOT justify invention. If `project_map(path)`
  shows `mark_compacted`, do not answer with `compact` — different
  names.
- The `imports: ...` line in `project_map(path)` output is GROUND TRUTH for
  intra-project dependencies. If X's imports don't list Y, then X
  doesn't use Y — never claim or draw otherwise.
- Pattern recognition is NOT a source of truth: a class that looks
  like a dataclass / BaseModel — you might "know" the body, you do
  not. Call read_file before reproducing more than a signature.
  (A separate HOOK rejects code blocks emitted without a prior read.)
- Not sure which file/symbol? Ask. Sure? Call the tool first,
  answer second.
- When the user CLARIFIES on a follow-up ("именно …", "конкретно",
  "I meant …", "specifically …"), do NOT recycle the previous
  turn — your prior answer missed the thing. Run NEW tool calls
  (grep, goto_definition, project_map on different files) first.
  Probe 2026-05-11: model answered "specifically the compression
  algorithm" by repeating session.py instead of grep'ing `compact`
  to locate StepAgent.compact().

Diagrams — pick the right Mermaid type. TUI renders fenced mermaid
inline via its own ASCII parser.
- `flowchart TD` / `flowchart LR` — FLOW & connections (components,
  workflow, control flow, dependency graphs). Syntax:
  `A[Label] --> B`, `A{Decision} -->|yes| B`, `A --- B`.
- `sequenceDiagram` — ACTORS & time (user journey, request/response,
  inter-object calls). Syntax: `participant Alice`,
  `Alice->>Bob: Req`, `Bob-->>Alice: Resp`, `Note over A,B: …`.
- `classDiagram` — class STRUCTURE (inheritance, composition,
  public API). Syntax: `class Name { +method() +field: int }`,
  `Parent <|-- Child`, `Container *-- Item`, `Owner o-- Asset`.
Out of scope (renderer doesn't support): stateDiagram, gantt,
journey, gitgraph, mindmap, erDiagram. For states, use flowchart
with decisions.
NEVER draw ASCII-art boxes-and-arrows by hand — emit fenced
```mermaid blocks only; the TUI renders them.
Before claiming "X uses Y" in a diagram, call `project_map(X)` and
check `imports:` — otherwise the diagram lies. Probe 2026-05-11:
model drew classifier.py as used-by agent.py, but agent.py's
`imports:` doesn't list it — classifier.py is an orphan.

To modify a file, output one or more SEARCH/REPLACE blocks. Each
block has three parts: (a) filename on its own line, EXACTLY as it
appears in the MAP, at column 0; (b) a ```python fence at column 0;
(c) SEARCH/REPLACE body, then closing ``` at column 0. The SEARCH
body must reproduce the file's lines with ORIGINAL indentation —
copy from read_file output.

Reference shape (documentation, not output — your real block omits
this framing and starts at column 0):

    helpers.py
    ```python
    <<<<<<< SEARCH
    def greet(name):
        return f"Hello, {name}"
    =======
    def greet(name, greeting="Hello"):
        return f"{greeting}, {name}"
    >>>>>>> REPLACE
    ```

Rules:
- SEARCH must match the file character-for-character (bodies,
  indentation, blank lines, trailing colons). The MAP only shows
  signatures — never copy them into SEARCH; read_file first.
- New file: leave SEARCH empty.
- Prefer multiple small blocks. For questions that need no file
  changes, respond with plain text only — no blocks."""


_REVIEW_MODE_ADDENDUM = """\

You are currently in REVIEW mode. Your job is to review code critically —
find real problems, not reassure. Never propose SEARCH/REPLACE patches.

Workflow:
1. Read the relevant files (read_file, grep, project_map). Don't review blind.
2. Output a structured review:

## Summary
One sentence: what this code does and whether it's solid.

## Issues
List real problems found. Each issue: severity tag + location + explanation.

Severity tags:
- [bug]      — incorrect behaviour, likely to cause failures
- [risk]     — won't crash today but will cause trouble (race, edge case, perf)
- [design]   — coupling, abstraction leak, hard to extend
- [nit]      — style, naming, minor clarity issue

Format each as:
- [severity] `file.py:line` — description. Impact: what breaks or degrades.

If you find nothing: say so explicitly ("No issues found") — don't manufacture fake nits.

## Suggestions
Optional. Only if there's a non-obvious improvement worth considering.
One bullet per suggestion. Keep it short.

Rules:
- No SEARCH/REPLACE. No code blocks with proposed changes. Review only.
- Call out the specific line or function, not a vague area.
- "This looks fine" is not a review. Find the real edge cases.
- If the user asked about a specific area, focus there first."""

_PLAN_MODE_ADDENDUM = """\

You are currently in PLAN mode. Your job is to produce a structured task
breakdown — NOT to write code or SEARCH/REPLACE blocks.

Output exactly this format (Markdown), one ## T-prefixed heading per task,
each task with the same five-line shape:

## T001: <short imperative title>

Goal: <one-line description of the outcome>
Files: <comma-separated list of project files this task touches>
Acceptance:
- <bullet 1 — observable test or behaviour>
- <bullet 2>
Test command: <pytest command that proves done, or "manual" if N/A>

## T002: ...

Rules for plan mode:
- 3-7 tasks total — split big work, but don't over-fragment.
- Each task self-contained: a separate person could pick one up.
- Files: real paths from the MAP. If a task needs new files, list the
  path you'll create.
- NO SEARCH/REPLACE blocks. NO code. Just the plan. The user will
  switch to code mode to execute each task.
- You MAY call read_file / grep to understand the project before
  planning — that's encouraged. Don't plan blind."""


@dataclass(frozen=True)
class PatchAttempt:
    """One iteration of the code_with_retry loop. Records what the model
    proposed, whether the patch applied, and what the tests said after.

    `edits` is a tuple so `frozen=True` is honest — a `list` field
    would still let callers mutate the contents in place, silently
    invalidating any cached view of the attempt history."""

    edits: tuple[Edit, ...]
    apply_ok: bool
    apply_error: str  # "" when apply_ok
    test_output: str  # "" when tests not run (apply failed)
    tests_passed: bool


@dataclass(frozen=True)
class StepResult:
    reply: str
    edits: list[Edit]
    response: ChatResponse
    # Empty for non-retry paths (regular ask / first-shot success). Populated
    # by code_with_retry so the TUI can show patch+test history.
    attempts: tuple[PatchAttempt, ...] = ()
    # All tool calls fired during this turn (read-only + mutating alike).
    # Used by _classify_outcome to detect shell_exec-based work that left
    # no SEARCH/REPLACE trace in the text reply.
    tool_results: tuple[ToolExecuted, ...] = ()

    @property
    def patch(self) -> list[Edit] | None:
        return self.edits if self.edits else None


@dataclass(frozen=True)
class TaskOutcome:
    """Result of one run-plan iteration over a `Task`. `step_result` is
    None when the task was skipped (e.g. plan-modified mid-run stopped
    the loop before this task started).

    `status` values:
      - "done"    — `code_with_retry` returned with a passing patch
      - "failed"  — `code_with_retry` exhausted retries
      - "skipped" — model emitted no edits (treated as "question, not
        a patch") or the task never started because the loop stopped
    """

    task: Task
    step_result: StepResult | None
    status: str


@dataclass(frozen=True)
class RunPlanResult:
    """Aggregate of a single run-plan invocation.

    `stopped_reason` reflects WHY the loop stopped:
      - "all_done"      — every non-done task completed (or was skipped)
      - "max_failures"  — N consecutive task failures hit the cap
      - "max_tasks"     — max_tasks limit reached (e.g. "next task" mode)
      - "cancelled"     — user pressed Esc; partial progress on disk
      - "plan_modified" — TASKS.md hash changed mid-run (user editor race)
      - "no_tasks"      — file missing or empty; nothing to do
    """

    outcomes: tuple[TaskOutcome, ...]
    stopped_reason: str
    tasks_completed: int


@dataclass(frozen=True)
class TextDelta:
    """Streaming chunk of model text, character/token-level."""

    text: str


@dataclass(frozen=True)
class ToolExecuted:
    """A tool call the model emitted, paired with its result. Yielded once
    per call after we've executed it."""

    call: ToolCall
    result: ToolResult


@dataclass(frozen=True)
class UsageReport:
    """Real token usage from the provider, aggregated across every tool-call
    round of a single `stream_ask` turn. Yielded once at end-of-stream so the
    TUI can record exact numbers instead of estimating from char counts."""

    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class RetryNotice:
    """Emitted when the enforce-read-before-show HOOK rolls a turn back and
    asks the model to read `path` first. The TUI surfaces this as an inline
    notice so the user understands why a second stream starts after the
    first one looked complete."""

    path: str


StreamItem = TextDelta | ToolExecuted | UsageReport | RetryNotice


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


# Cap on the args-summary segment inside a compression marker. A
# `grep(pattern="...500 chars...")` would otherwise blow past a sane
# terminal line. We truncate; the model still has the tool name + first
# output line to recognise what was compressed.
_ARGS_SUMMARY_MAX = 80


def _summarize_tool_args(raw_args: str) -> str:
    """Render a tool-call's JSON arguments as a brief `k=v, k=v` string.

    Tool args arrive from the LLM as a JSON string ("native function
    calling" pass-through). We parse leniently — a malformed payload
    falls back to the raw string so the marker still carries SOMETHING
    identifying. Long values are truncated; nested structures are
    rendered as `<dict>` / `<list>` rather than dumped verbatim (a
    nested payload in a marker is its own bloat).
    """
    if not raw_args:
        return ""
    try:
        parsed = json.loads(raw_args)
    except json.JSONDecodeError:
        return _truncate_args(raw_args, _ARGS_SUMMARY_MAX)
    if not isinstance(parsed, dict):
        return _truncate_args(str(parsed), _ARGS_SUMMARY_MAX)
    parts: list[str] = []
    for k, v in parsed.items():
        if isinstance(v, str):
            rendered = v
        elif isinstance(v, int | float | bool) or v is None:
            rendered = str(v)
        elif isinstance(v, dict):
            rendered = "<dict>"
        elif isinstance(v, list):
            rendered = "<list>"
        else:
            rendered = str(v)
        parts.append(f"{k}={rendered}")
    return _truncate_args(", ".join(parts), _ARGS_SUMMARY_MAX)


def _truncate_args(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _atomic_write(path: Path, content: str) -> None:
    """Write through a `.tmp` sibling then rename. Mirrors AgentState.save —
    a partial write during cancel must NOT leave TASKS.md half-rewritten."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


def _build_task_prompt(task: Task) -> str:
    """One run-plan iteration's prompt to the code-mode agent. We keep
    it close to the planner's own task shape so the model sees its own
    output framed as the request — no translation layer, no drift."""
    parts = [f"Execute task {task.id}: {task.title}"]
    body = task.body.strip()
    if body:
        parts.append(body)
    return "\n\n".join(parts)


# Tools that indicate real work was done (files created/modified or
# commands executed). Read-only tools (read_file, grep, project_map …)
# are intentionally absent — they don't change the workspace.
_MUTATING_TOOLS = frozenset({"shell_exec"})


def _missing_file_paths(tool_results: tuple[ToolExecuted, ...]) -> list[str]:
    """Return file paths from failed read_file calls where the file was not found.

    Used to detect the pattern: model tries to read a file that doesn't
    exist yet → we re-prompt it to create the file instead of giving up.
    """
    paths: list[str] = []
    for r in tool_results:
        if r.call.name != "read_file" or r.result.ok:
            continue
        if "not found" not in r.result.output.lower():
            continue
        try:
            args = json.loads(r.call.body)
            path = args.get("path", "")
            if path:
                paths.append(path)
        except (json.JSONDecodeError, KeyError, AttributeError):
            pass
    return paths


def _classify_outcome(task: Task, step_result: StepResult) -> TaskOutcome:
    """Decide done / failed / skipped from a `code_with_retry` return.

    SEARCH/REPLACE path (attempts present):
      - Last attempt passed tests → "done".
      - Otherwise → "failed".

    Shell-exec path (no SEARCH/REPLACE blocks emitted):
      - Any shell_exec calls ran AND all succeeded → "done" (model used
        shell commands to create/modify files instead of patches).
      - Any shell_exec calls ran BUT at least one failed → "failed"
        (model attempted something and it broke).
      - No mutating tool calls at all → "skipped" (model answered in
        plain text without touching the workspace).
    """
    attempts = step_result.attempts
    if not attempts:
        shell_calls = [
            r for r in step_result.tool_results if r.call.name in _MUTATING_TOOLS
        ]
        if not shell_calls:
            return TaskOutcome(task=task, step_result=step_result, status="skipped")
        if all(r.result.ok for r in shell_calls):
            return TaskOutcome(task=task, step_result=step_result, status="done")
        return TaskOutcome(task=task, step_result=step_result, status="failed")
    if attempts[-1].tests_passed:
        return TaskOutcome(task=task, step_result=step_result, status="done")
    return TaskOutcome(task=task, step_result=step_result, status="failed")


class StepAgent:
    """Multi-turn agent: model can call read_file, then produces SEARCH/REPLACE.

    Keeps a `history` of (user_task, assistant_reply) pairs across turns so the
    model can reference previous exchanges. Tool-call round-trips inside a single
    ask() do NOT enter the history — they are internal to that turn.
    """

    def __init__(
        self,
        llm: LLMAdapter,
        cwd: Path,
        config: AppConfig,
        *,
        shell_runner: ShellRunner | None = None,
        memory: MemoryStore | None = None,
        confirm_shell_exec: ConfirmShellExec | None = None,
    ) -> None:
        self._llm = llm
        self._cwd = cwd
        self._config = config
        # Optional shell runner override — used by tests and by callers that
        # want to point pytest at a sandbox. When None, agent_tools.execute
        # constructs the default AsyncShellRunner per tool call.
        self._shell_runner = shell_runner
        # Optional pluggable memory layer. When set, each turn does a
        # cheap top-3 FTS5 lookup on the user's task and prepends any
        # hits as a "Recalled notes" block — facts the user told us
        # ("when you touch X always update Y", project conventions,
        # past decisions) ride along automatically. None disables it
        # entirely so tests / lightweight callers don't take the cost.
        self._memory = memory
        # Awaitable confirmation hook for `shell_exec` in skeptic mode.
        # The TUI provides one that mounts a ShellExecCard and awaits
        # the user's [a]/[r] decision; headless callers leave it None
        # and skeptic-mode shell_exec calls are refused.
        self._confirm_shell_exec = confirm_shell_exec
        # Mixed-role transcript: user / assistant / tool / assistant-with-
        # tool_calls. The list flows straight into the next turn's
        # `_initial_messages`, so the shape must be a valid OpenAI-style
        # conversation (every `tool` message preceded by an assistant
        # message that emitted the matching tool_call id). The
        # `compress_tool_results` hook rewrites stale tool entries in
        # place; the round-trip shape is preserved.
        self._history: list[dict[str, Any]] = []
        # Cross-turn record of every relative path the model has called
        # `read_file` on. Used by the enforce-read-before-show HOOK so a
        # turn-2 patch on file X is grounded if X was read in turn-1.
        # Cleared by `clear_history` and replaced when `compact` collapses
        # history — both points where we lose the conversational context
        # that made past reads load-bearing.
        self._read_files_history: set[str] = set()

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()
        self._read_files_history.clear()

    def attach_memory(self, store: MemoryStore | None) -> None:
        """Swap or detach the auto-recall memory store. The TUI builds
        MemoryStore lazily on first /remember/ /recall — when that
        happens after the agent is already constructed, this is the
        public hook for handing it over. Pass None to detach."""
        self._memory = store

    async def ask(
        self,
        task: str,
        *,
        mode: str = "ask",
        on_tool_executed: Callable[[ToolCall, ToolResult], None] | None = None,
    ) -> StepResult:
        """Non-streaming entrypoint — collects `stream_ask` into a StepResult.

        Both the streaming TUI and the non-streaming callers (probe, bench,
        `code_with_retry`) now share one engine: HOOK, history bookkeeping,
        tool-result compression and usage tracking live in `stream_ask` and
        apply uniformly regardless of who's listening for chunks. The plan-
        saving side-effect is handled inside `stream_ask`; we don't repeat
        it here.

        `on_tool_executed` fires synchronously for every tool call that
        resolves during this turn — lets callers (e.g. `_run_plan` in the
        TUI) surface tool cards in real-time rather than waiting for the
        whole turn to finish."""
        reply_parts: list[str] = []
        tool_results: list[ToolExecuted] = []
        usage: UsageReport | None = None
        async for item in self.stream_ask(task, mode=mode):
            if isinstance(item, TextDelta):
                reply_parts.append(item.text)
            elif isinstance(item, ToolExecuted):
                tool_results.append(item)
                if on_tool_executed is not None:
                    with suppress(Exception):
                        on_tool_executed(item.call, item.result)
            elif isinstance(item, RetryNotice):
                # HOOK fired — discard the first attempt's text and keep
                # only what the retry produces. This matches how the
                # previous non-stream HOOK worked (it returned just the
                # second pass).
                reply_parts.clear()
            elif isinstance(item, UsageReport):
                usage = item
        reply = "".join(reply_parts)
        edits = extract_edits(reply)
        response = ChatResponse(
            content=reply,
            prompt_tokens=usage.prompt_tokens if usage is not None else 0,
            completion_tokens=usage.completion_tokens if usage is not None else 0,
            cost=None,
        )
        return StepResult(
            reply=reply,
            edits=edits,
            response=response,
            tool_results=tuple(tool_results),
        )

    async def code_with_retry(
        self,
        task: str,
        *,
        mode: str = "code",
        on_tool_executed: Callable[[ToolCall, ToolResult], None] | None = None,
        force_loop: bool = False,
    ) -> StepResult:
        """Iterative patch loop: ask the model, apply, run tests, retry on failure.

        Up to ``agent.max_debug_attempts`` retries (in addition to the initial
        attempt — so ``max_debug_attempts=2`` means at most 3 total model
        calls). Stops as soon as a patch applies AND tests pass. Each
        iteration's outcome is recorded on the returned ``StepResult.attempts``
        tuple so the TUI can render a history view.

        When the model returns no SEARCH/REPLACE blocks we treat it as a
        plain-text answer and return immediately — there's nothing to apply
        and nothing to retry. The successful tail iteration returns
        ``StepResult.edits == []`` because the patch is already on disk; the
        caller has no reason to re-apply.

        The retry path is gated on ``agent.iterative_patch_loop``; when off,
        this method falls back to a single ``ask`` call so callers can switch
        on the method unconditionally without surprising existing users.
        """
        if not (self._config.agent.iterative_patch_loop or force_loop):
            return await self.ask(task, mode=mode, on_tool_executed=on_tool_executed)

        max_retries = max(0, self._config.agent.max_debug_attempts)
        attempts: list[PatchAttempt] = []
        prompt = task
        # Lazy pre-loop snapshot of every file we end up touching. Lets us
        # roll back to the original state if the loop exhausts retries —
        # otherwise the workspace ends up with N-1 cumulative half-applied
        # patches and the user can only [r]eject the LAST diff that the
        # TUI surfaces, leaving the earlier mutations silently on disk.
        pre_loop_snapshot: dict[Path, str | None] = {}

        def _snapshot_targets(edits: list[Edit]) -> None:
            for edit in edits:
                target = self._cwd / edit.path
                if target in pre_loop_snapshot:
                    continue
                if target.is_file():
                    try:
                        pre_loop_snapshot[target] = target.read_text()
                    except OSError:
                        pre_loop_snapshot[target] = None  # treat as "did not exist"
                else:
                    pre_loop_snapshot[target] = None

        # Initial attempt + up to max_retries retries.
        last_result: StepResult | None = None
        for i in range(max_retries + 1):
            result = await self.ask(prompt, mode=mode, on_tool_executed=on_tool_executed)
            last_result = result
            if not result.edits:
                # Check for failed read_file calls on non-existent files.
                # Model tried to read a file that doesn't exist yet — tell it
                # to create those files and retry (once).
                if i < max_retries:
                    missing = _missing_file_paths(result.tool_results)
                    if missing:
                        prompt = _MISSING_FILES_PROMPT.format(paths=", ".join(missing))
                        continue
                # Plain text or gave up — nothing to retry on.
                return result

            _snapshot_targets(result.edits)
            ok, err = apply_edits(result.edits, self._cwd)
            if not ok:
                attempts.append(
                    PatchAttempt(
                        edits=tuple(result.edits),
                        apply_ok=False,
                        apply_error=err,
                        test_output="",
                        tests_passed=False,
                    )
                )
                if i == max_retries:
                    break
                prompt = _APPLY_FAILED_PROMPT.format(error=err)
                continue

            test_output, tests_passed = await self._run_tests()
            attempts.append(
                PatchAttempt(
                    edits=tuple(result.edits),
                    apply_ok=True,
                    apply_error="",
                    test_output=test_output,
                    tests_passed=tests_passed,
                )
            )
            if tests_passed:
                if (
                    self._config.agent.require_tests
                    and i < max_retries
                    and _changes_include_prod_code(result.edits)
                    and not _changes_include_tests(result.edits)
                ):
                    # Code changed, no test changed — retry asking for one.
                    # The applied production patch stays on disk; the next
                    # iteration produces an additive test patch on top.
                    prompt = _NEEDS_TESTS_PROMPT
                    continue
                # Patch is on disk; clear edits so the caller doesn't re-apply.
                return StepResult(
                    reply=result.reply,
                    edits=[],
                    response=result.response,
                    attempts=tuple(attempts),
                )
            if i == max_retries:
                break
            prompt = _TESTS_FAILED_PROMPT.format(output=test_output)

        # Exhausted retries. Roll the workspace back to its pre-loop state
        # so a `git diff` is clean for the user to inspect — the attempts
        # history still carries every patch so the TUI can render what
        # was tried and let the user re-apply any of them by hand.
        for target, original in pre_loop_snapshot.items():
            try:
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_text(original)
            except OSError:
                continue
        # Surface the last attempt verbatim so the TUI can show "tests
        # still red after N tries" plus the diff/output history.
        assert last_result is not None
        return StepResult(
            reply=last_result.reply,
            edits=last_result.edits,
            response=last_result.response,
            attempts=tuple(attempts),
        )

    async def run_plan(
        self,
        *,
        stop_after_failures: int = 2,
        max_tasks: int | None = None,
        on_task_start: Callable[[Task], None] | None = None,
        on_task_end: Callable[[TaskOutcome], None] | None = None,
        on_tool_executed: Callable[[ToolCall, ToolResult], None] | None = None,
    ) -> RunPlanResult:
        """Walk `.code-scalpel/TASKS.md` and execute each non-done task
        through `code_with_retry`. Marks completed tasks `[✓]` in the
        file atomically (write `.tmp` → rename).

        Stop conditions:
          - `stop_after_failures` consecutive task failures → "max_failures"
          - `asyncio.CancelledError` propagates → already-marked tasks
            stay marked, in-flight `code_with_retry` rolls back its own
            workspace via the existing snapshot path.
          - TASKS.md hash changes between iterations → "plan_modified"
            (defends against the user editing the file in another
            window mid-run).
          - All non-done tasks consumed → "all_done".
          - File missing or empty → "no_tasks" (no exception).

        Optional `on_task_start` / `on_task_end` hooks let the TUI render
        progress inline without re-reading the file or re-parsing the
        outcomes tuple. The hooks fire synchronously around each
        `code_with_retry` call; exceptions inside them are swallowed so
        a buggy widget can't kill the autonomous loop.
        """
        tasks_path = self._cwd / ".code-scalpel" / "TASKS.md"
        if not tasks_path.is_file():
            return RunPlanResult(outcomes=(), stopped_reason="no_tasks", tasks_completed=0)

        original_text = tasks_path.read_text()
        initial_hash = _hash_text(original_text)
        tasks = parse_tasks_md(original_text)
        if not tasks or all(t.done for t in tasks):
            reason = "no_tasks" if not tasks else "all_done"
            return RunPlanResult(outcomes=(), stopped_reason=reason, tasks_completed=0)

        outcomes: list[TaskOutcome] = []
        consecutive_failures = 0
        # Mutable list so we can flip individual tasks done without
        # rebuilding the tuple every iteration.
        live_tasks: list[Task] = list(tasks)
        stopped_reason = "all_done"

        for idx, task in enumerate(live_tasks):
            if task.done:
                continue

            # Fire start-hook BEFORE the modification check so the TUI
            # has its "● Running T00N…" line on screen the moment we
            # commit to attempting this task. The check below is the
            # last gate.
            if on_task_start is not None:
                with suppress(Exception):
                    on_task_start(task)

            # Plan-modification detection — re-read before each task. If
            # the file changed under us, stop. Already-marked tasks stay
            # on disk; the user's edits win the race.
            current_text = tasks_path.read_text()
            if _hash_text(current_text) != initial_hash:
                stopped_reason = "plan_modified"
                break

            prompt = _build_task_prompt(task)
            try:
                step_result = await self.code_with_retry(
                    prompt,
                    mode="code",
                    on_tool_executed=on_tool_executed,
                    force_loop=True,
                )
            except Exception:
                # Surface to the caller — cancellation propagates,
                # arbitrary failures stop the loop with a record.
                raise

            outcome = _classify_outcome(task, step_result)
            outcomes.append(outcome)
            if on_task_end is not None:
                with suppress(Exception):
                    on_task_end(outcome)

            if outcome.status == "done":
                live_tasks[idx] = Task(id=task.id, title=task.title, body=task.body, done=True)
                # Persist atomically. We refresh `initial_hash` against
                # OUR own write so the plan-modification check doesn't
                # trip on the very change we just made.
                new_text = serialize_tasks(tuple(live_tasks), current_text)
                _atomic_write(tasks_path, new_text)
                initial_hash = _hash_text(new_text)
                consecutive_failures = 0
            elif outcome.status == "failed":
                consecutive_failures += 1
                if consecutive_failures >= stop_after_failures:
                    stopped_reason = "max_failures"
                    break
            else:
                # "skipped" — model decided no patch needed. Doesn't
                # count toward failure budget; we move on.
                consecutive_failures = 0

            if max_tasks is not None and len(outcomes) >= max_tasks:
                stopped_reason = "max_tasks"
                break

        completed = sum(1 for o in outcomes if o.status == "done")
        return RunPlanResult(
            outcomes=tuple(outcomes),
            stopped_reason=stopped_reason,
            tasks_completed=completed,
        )

    async def _run_tests(self) -> tuple[str, bool]:
        """Invoke the run_tests tool and return (output, passed)."""
        call = ToolCall(name="run_tests", body="{}")
        result = await execute(
            call,
            self._cwd,
            max_lines=self._config.agent.max_file_lines,
            runner=self._shell_runner,
        )
        return result.output, result.ok

    async def _compress_old_tool_results(self) -> int:
        """Walk `self._history` and replace stale tool-role messages
        with a compact marker. Returns the number of messages rewritten
        — useful for tests and for future telemetry.

        Turn-boundary tracking: history is a flat list. A "turn" begins
        at every user-role entry. We label each tool message with the
        index of the user-turn it belongs to (0-based — the first user
        message starts turn 0). The CURRENT turn is the highest-numbered
        one; `age = current_turn - message_turn`. Compression fires
        when age strictly exceeds the configured threshold AND the
        payload meets the size minimum.

        When `agent.compress_with_llm` is on, each compressed message
        gets an LLM-generated one-line summary as the marker hint
        instead of the deterministic first-line. On any failure
        (network, empty reply) the deterministic path is reused — a
        broken summariser never blocks the compress pass.
        """
        cfg = self._config.agent
        # Assign each entry its owning turn index.
        turn_idx = -1
        entry_turns: list[int] = []
        for entry in self._history:
            if entry.get("role") == "user":
                turn_idx += 1
            entry_turns.append(turn_idx)
        if turn_idx < 0:
            return 0
        current_turn = turn_idx
        compressed = 0
        for i, entry in enumerate(self._history):
            if entry.get("role") != "tool":
                continue
            content = entry.get("content")
            if not isinstance(content, str):
                continue
            age = current_turn - entry_turns[i]
            if not should_compress(
                content,
                age,
                threshold_turns=cfg.compress_tool_results_after_turns,
                min_chars=cfg.compress_tool_results_min_chars,
            ):
                continue
            tool_name = entry.get("_tool_name", "tool")
            tool_args = entry.get("_tool_args", "")
            args_summary = _summarize_tool_args(tool_args)
            hint: str | None = None
            if cfg.compress_with_llm:
                summary = await summarize_with_llm(content, self._llm)
                # Empty summary → fall back to deterministic (hint=None).
                hint = summary if summary else None
            entry["content"] = compress_tool_message(
                content,
                tool_name=str(tool_name),
                args_summary=args_summary,
                turn=entry_turns[i],
                hint=hint,
            )
            compressed += 1
        return compressed

    @staticmethod
    def _is_loop(tcs: tuple[NativeToolCall, ...], seen: set[tuple[str, str]]) -> bool:
        looped = False
        for tc in tcs:
            key = (tc.name, tc.arguments)
            if key in seen:
                looped = True
            seen.add(key)
        return looped

    async def _execute_native(self, tc: NativeToolCall) -> ToolResult:
        call = ToolCall(name=tc.name, body=tc.arguments)
        return await execute(
            call,
            self._cwd,
            max_lines=self._config.agent.max_file_lines,
            runner=self._shell_runner,
            trust=self._config.agent.trust,
            shell_exec_timeout=self._config.agent.shell_exec_timeout,
            confirm_shell_exec=self._confirm_shell_exec,
        )

    def _tool_schemas(self) -> list[dict[str, Any]]:
        """Build the tool list per request. `shell_exec` now ships at
        all three trust levels — skeptic gates each call through the
        confirmation callback registered at construction time (the
        TUI provides one; headless callers like probe/bench leave it
        `None` and shell_exec refuses in skeptic)."""
        return [*TOOL_SCHEMAS, SHELL_EXEC_SCHEMA]

    def _remember(self, user_msg: str, assistant_msg: str) -> None:
        self._history.append({"role": "user", "content": user_msg})
        self._history.append({"role": "assistant", "content": assistant_msg})

    def _rollback_last_turn(self) -> None:
        """Drop everything from the most recent user-role entry onward.
        Used by the enforce-read-before-show HOOK so the unread reply
        we're about to retry doesn't end up in the official conversation
        trail. A turn may contain user + assistant only, OR user +
        assistant(tool_calls) + tool* + assistant — both shapes are
        handled by walking back to the last user boundary."""
        for i in range(len(self._history) - 1, -1, -1):
            if self._history[i].get("role") == "user":
                del self._history[i:]
                return

    def _note_read_file(self, tc: NativeToolCall, result: ToolResult) -> None:
        """Record a successful `read_file(path)` call so the HOOK knows the
        model has grounded against that file. We log only ok=True calls —
        an errored read_file (path missing, permission denied) didn't put
        any content in context, so a subsequent patch is still fabricating.
        """
        if tc.name != "read_file" or not result.ok:
            return
        try:
            args = json.loads(tc.arguments) if tc.arguments else {}
        except json.JSONDecodeError:
            return
        path = args.get("path") if isinstance(args, dict) else None
        if isinstance(path, str) and path:
            self._read_files_history.add(path)

    def _check_read_before_show(self, task: str, reply: str) -> str | None:
        """Return a re-prompt string if the reply emits a code block for a
        file the model never read, else None.

        Logic:
          - SEARCH/REPLACE blocks: target file comes from the existing
            edit-block parser. If ANY target is unread, fire — we'd
            rather over-trigger and force one extra read than let a
            multi-file patch through where one of the files is
            fabricated. The re-prompt mentions the first unread path;
            in practice a model that re-reads one file usually re-reads
            the rest of the block too.
          - Bare ```python fences with no SEARCH/REPLACE: only fire when
            the user's task explicitly names a project file. A fence
            with no project anchor is conversational example code (e.g.
            "show me a list comprehension") and HOOK enforcement there
            would be pure noise.
        """
        # Edit blocks first — these are the high-confidence case.
        edits = extract_edits(reply)
        if edits:
            for edit in edits:
                if edit.path not in self._read_files_history:
                    return _READ_BEFORE_SHOW_PROMPT.format(path=edit.path)
            return None
        # No edit blocks: look for a bare fenced python block AND a
        # project-file mention in the task.
        if not _BARE_PY_FENCE_RE.search(reply):
            return None
        target = self._task_target_file(task)
        if target is None:
            return None
        if target in self._read_files_history:
            return None
        return _READ_BEFORE_SHOW_PROMPT.format(path=target)

    def _task_target_file(self, task: str) -> str | None:
        """Pick a project file mentioned by name in the user's task, or
        None if the task is generic. We scan the lightweight overview
        (paths only) — symbol-level matching would need the full map and
        belongs in a separate pass."""
        from code_scalpel.tools.files import list_files

        try:
            files = list_files(self._cwd, max_files=200)
        except OSError:
            return None
        # Sort by length descending so "pkg/foo.py" wins over "foo.py"
        # when both appear in the project — the longer match is more
        # specific.
        for rel in sorted((str(p) for p in files), key=len, reverse=True):
            if rel in task:
                return rel
        return None

    async def compact(self) -> str | None:
        """Summarize history into a short note and replace it. Returns summary
        text, or None if history is empty."""
        if not self._history:
            return None
        joined = "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in self._history)
        msgs = [
            {
                "role": "system",
                "content": (
                    "Summarize the following coding-assistant conversation in 5-10 short "
                    "bullets. Focus on: what the user asked, what was decided, what files "
                    "were touched. Do NOT add commentary. Output the bullets only."
                ),
            },
            {"role": "user", "content": joined},
        ]
        profile = self._config.current_profile
        # Compact is a summarization task — use ask-mode (low) temperature.
        response = await self._llm.chat(msgs, **profile.inference_kwargs("ask"))
        summary = response.content.strip()
        self._history = [
            {
                "role": "user",
                "content": f"Summary of the earlier session:\n{summary}",
            }
        ]
        # Compacted history loses the tool-call provenance — the model
        # can no longer point at "we read file X earlier". Drop the read
        # record so the HOOK forces a fresh read on the first post-compact
        # patch instead of trusting a memory that's been collapsed.
        self._read_files_history.clear()
        return summary

    async def stream_ask(self, task: str, *, mode: str = "ask") -> AsyncIterator[StreamItem]:
        """Canonical turn engine — used by both the streaming TUI and the
        non-streaming `ask()` wrapper.

        Yields typed events:
          - `TextDelta` for model output chunks
          - `ToolExecuted` after each tool call resolves
          - `RetryNotice` when the enforce-read-before-show HOOK rolls the
            turn back and a second stream is about to begin
          - `UsageReport` once at end-of-turn with aggregated provider usage

        HOOK + tool-result compression now live here too, so every entry
        point (TUI, probe, bench, `code_with_retry`) benefits from them —
        previously the HOOK only ran in the non-streaming `ask()` path,
        which left the TUI silently un-protected from the same hallucinate-
        before-reading failure mode the HOOK was added to catch.
        """
        prompt_total = 0
        completion_total = 0

        attempt_task = task
        final_assistant = ""
        for attempt in range(2):
            # Run one tool loop. The helper yields chunks back to us as it
            # streams; we re-yield them to our own consumer and read the
            # aggregates back through `collected` once it's done.
            collected: dict[str, Any] = {}
            async for item in self._run_tool_loop(attempt_task, mode, collected):
                yield item
            final_assistant = collected.get("final_assistant", "")
            prompt_total = collected.get("prompt_total", 0) or prompt_total
            completion_total += collected.get("completion_total", 0)

            # HOOK — only fires once, second iteration is the retry and
            # whatever it produces is final.
            if attempt == 0 and self._config.agent.enforce_read_before_show:
                reprompt = self._check_read_before_show(task, final_assistant)
                if reprompt is not None:
                    # Drop the unread reply from history so the
                    # hallucinated patch doesn't look like a committed
                    # turn, and tell the consumer we're retrying.
                    self._rollback_last_turn()
                    yield RetryNotice(path=self._extract_retry_path(reprompt))
                    attempt_task = reprompt
                    continue
            break

        # Compression last — must NEVER break the turn, so any failure in
        # the marker construction is swallowed. We trade exact recall of
        # an old tool output for a kilo-tokens of headroom.
        if self._config.agent.compress_tool_results:
            with suppress(Exception):
                await self._compress_old_tool_results()

        if mode == "plan":
            self._maybe_save_plan(final_assistant)

        # Emit aggregate usage last so the TUI can record real numbers
        # alongside the turn summary it draws right after the stream ends.
        yield UsageReport(
            prompt_tokens=prompt_total,
            completion_tokens=completion_total,
        )

    async def _run_tool_loop(
        self,
        task: str,
        mode: str,
        out: dict[str, Any],
    ) -> AsyncIterator[StreamItem]:
        """One full tool-calling loop against the LLM stream.

        Yields TextDelta / ToolExecuted up to the consumer; mutates `out`
        with the aggregate numbers the caller needs after the stream ends
        (`final_assistant`, `prompt_total`, `completion_total`). Splitting
        this out lets `stream_ask` retry the loop once when the HOOK fires
        without duplicating the round-management code.
        """
        user_msg = self._user_message(task)
        messages = self._initial_messages(user_msg, mode=mode)
        profile = self._config.current_profile

        # Commit the bare task to history up-front so any tool messages
        # we record below have their owning user-turn boundary in place.
        # The full user_msg (task + recalled notes) goes to the LLM only —
        # history keeps the bare task so subsequent turns aren't padded.
        turn_history: list[dict[str, Any]] = [{"role": "user", "content": task}]

        final_assistant = ""
        prompt_total = 0
        completion_total = 0

        seen: set[tuple[str, str]] = set()
        for _ in range(_MAX_TOOL_ROUNDS):
            full = ""
            round_tool_calls: list[NativeToolCall] = []
            async for chunk in self._llm.stream(
                messages,
                tools=self._tool_schemas(),
                **profile.inference_kwargs(mode, self._config.agent.thinking_effort),
            ):
                if chunk.text:
                    full += chunk.text
                    yield TextDelta(chunk.text)
                if chunk.tool_call is not None:
                    round_tool_calls.append(chunk.tool_call)
                if chunk.usage is not None:
                    # Each round's usage chunk reports the FULL prompt the
                    # model saw on that call; keep the latest as the prompt
                    # total and sum completion across rounds.
                    prompt_total = chunk.usage.prompt_tokens
                    completion_total += chunk.usage.completion_tokens

            asst_msg: dict[str, Any] = {"role": "assistant", "content": full or None}
            if round_tool_calls:
                asst_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in round_tool_calls
                ]
            messages.append(asst_msg)

            if not round_tool_calls:
                final_assistant = full
                break

            turn_history.append(asst_msg)

            if self._is_loop(tuple(round_tool_calls), seen):
                messages.append(_FORCE_ANSWER_MSG)
                final_assistant = full
                continue

            for tc in round_tool_calls:
                result = await self._execute_native(tc)
                self._note_read_file(tc, result)
                call_view = ToolCall(name=tc.name, body=tc.arguments)
                yield ToolExecuted(call_view, result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result.output,
                    }
                )
                turn_history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result.output,
                        "_tool_name": tc.name,
                        "_tool_args": tc.arguments,
                    }
                )
            final_assistant = full

        turn_history.append({"role": "assistant", "content": final_assistant})
        self._history.extend(turn_history)

        out["final_assistant"] = final_assistant
        out["prompt_total"] = prompt_total
        out["completion_total"] = completion_total

    @staticmethod
    def _extract_retry_path(reprompt: str) -> str:
        """Pull the path out of the HOOK reprompt for the UI label.

        The reprompt template is `_READ_BEFORE_SHOW_PROMPT.format(path=...)`.
        We extract the path so the UI can show *which* file the model needs
        to read. Falls back to "(file)" when the template changes — the
        notice still renders, just with less specificity."""
        m = re.search(r"`([^`]+)`", reprompt)
        return m.group(1) if m else "(file)"

    def _maybe_save_plan(self, reply: str) -> None:
        """Persist the planner's TASKS.md output to .code-scalpel/TASKS.md.

        Looks for the conventional "## T001:" first-task heading; if found,
        writes everything from that heading onward to disk. Anything before
        the first heading is conversational lead-in and gets dropped.
        Silent no-op when the reply doesn't contain a recognised plan
        (e.g. model asked a clarifying question)."""
        m = re.search(r"^##\s+T\d{3}:", reply, flags=re.MULTILINE)
        if m is None:
            return
        plan_text = reply[m.start() :].rstrip() + "\n"
        target_dir = self._cwd / ".code-scalpel"
        target = target_dir / "TASKS.md"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(plan_text)
        except OSError:
            # Best-effort; don't crash the turn over a write failure.
            pass

    def _initial_messages(self, user_msg: str, *, mode: str = "ask") -> list[dict[str, Any]]:
        # With native function-calling, tool docs come from the API schema —
        # we don't need few-shot examples of the text <TOOL: name> format.
        system = _SYSTEM_PROMPT
        if mode == "plan":
            system += _PLAN_MODE_ADDENDUM
        elif mode == "review":
            system += _REVIEW_MODE_ADDENDUM
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]
        # History may carry internal bookkeeping fields (`_tool_name`,
        # `_tool_args`) on tool messages for the compression pass. Strip
        # underscore-prefixed keys before handing the list to the LLM —
        # OpenAI-compat backends reject unknown fields on `tool` role.
        for entry in self._history:
            msgs.append({k: v for k, v in entry.items() if not k.startswith("_")})
        msgs.append({"role": "user", "content": user_msg})
        return msgs

    def _user_message(self, task: str) -> str:
        """Build the user message: task + optional pre-blocks.

        Two pre-blocks can prepend, both gated on having content:
          1. **Eager recipes** from `.code-scalpel/recipes/*.md` with
             `load: eager` — surfaces /learn-generated knowledge so
             the agent sees what the user (or a past `/learn` call)
             saved about technologies in this project.
          2. **Memory recall** — top-k FTS5 hits from /remember notes.

        Earlier iteration prepended a `Project files` overview (paths
        + line counts) every turn. Юзер flagged 2026-05-11: 800-1000
        tokens of "auto-mixed" project listing burying the task at
        the end. Same family of failure as the "Project map: <500
        lines>\\nTask: X" layout we already retired. We don't repeat
        that mistake — recipes and recall both stay quiet by default
        (zero output when no recipe / no recall hit).
        """
        from code_scalpel.recipes import format_recipes_block, recipes_for_turn

        try:
            recipes_block = format_recipes_block(recipes_for_turn(self._cwd, task))
        except Exception:
            # Recipe loading is best-effort: a syntax error in one file
            # must NOT break the turn. discover_recipes already swallows
            # most failure modes; this is the last-resort guard.
            recipes_block = ""

        recalled = self._recall_notes(task)
        if not recipes_block and not recalled:
            return task

        parts: list[str] = []
        if recipes_block:
            parts.extend([recipes_block, ""])
        parts.append(task)
        if recalled:
            parts.extend(["", "Recalled notes (from prior `/remember` calls):"])
            parts.extend(f"- {n}" for n in recalled)
        return "\n".join(parts)

    def _recall_notes(self, task: str, *, k: int = 3) -> list[str]:
        """Top-k memory hits for the current task. Swallows store errors —
        memory is a non-critical convenience layer, a broken FTS5 query
        must NOT break the turn.

        FTS5 defaults to AND-conjunction; a free-text task like "what to
        do before commit?" requires every word to match. We rewrite the
        query as OR over alpha-numeric tokens so a single shared word is
        enough to surface a stored note. Punctuation and stop-shaped
        chars are dropped — they're FTS5 operators and would corrupt the
        query.
        """
        if self._memory is None:
            return []
        tokens = re.findall(r"\w+", task, flags=re.UNICODE)
        if not tokens:
            return []
        query = " OR ".join(f'"{t}"' for t in tokens)
        try:
            hits = self._memory.search(query, k=k)
        except Exception:
            return []
        return [h.text for h in hits]

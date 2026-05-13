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
from code_scalpel import prompts as _prompts
from code_scalpel.llm.adapter import ChatResponse, LLMAdapter, NativeToolCall
from code_scalpel.patch.edit_block import Edit, apply_edits, extract_edits
from code_scalpel.plan import Task, parse_tasks_md, serialize_tasks
from code_scalpel.tools.agent_tools import (
    LOAD_SKILL_SCHEMA,
    SHELL_EXEC_SCHEMA,
    TOOL_SCHEMAS,
    UNLOAD_SKILL_SCHEMA,
    ConfirmShellExec,
    ToolCall,
    ToolResult,
    execute,
)
from code_scalpel.tools.shell import ShellRunner

_MAX_TOOL_ROUNDS = 6

# Prompt aliases — kept as module attributes for the moment so existing
# code (and tests that import these names) keeps working. The source of
# truth is `code_scalpel/prompts/`.
_APPLY_FAILED_PROMPT = _prompts.APPLY_FAILED
_TESTS_FAILED_PROMPT = _prompts.TESTS_FAILED
_MISSING_FILES_PROMPT = _prompts.MISSING_FILES
_NEEDS_TESTS_PROMPT = _prompts.NEEDS_TESTS


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
    "content": _prompts.FORCE_ANSWER,
}

# Re-prompt when the model emitted a code block targeting a file it never
# read. Weak local models fabricate bodies from training-data shape and
# we'd silently let through patches/snippets that don't match the actual
# source. The HOOK rejects the reply once, asks the model to ground via
# read_file, then accepts whatever it produces on the second pass.
_READ_BEFORE_SHOW_PROMPT = _prompts.READ_BEFORE_SHOW

# A fenced python block in a reply that has NO surrounding SEARCH/REPLACE
# markers. The HOOK only fires on such blocks when the user's task names a
# specific project file — otherwise the block is conversational example
# code (e.g. answering "how would I write a list comprehension?") and we
# don't have a target to enforce against.
_BARE_PY_FENCE_RE = re.compile(
    r"^[ \t]*```python\n(?P<body>.*?)\n[ \t]*```",
    re.DOTALL | re.MULTILINE,
)

_SYSTEM_PROMPT = _prompts.SYSTEM
_CODE_MODE_ADDENDUM = "\n\n" + _prompts.MODE_CODE
_REVIEW_MODE_ADDENDUM = "\n\n" + _prompts.MODE_REVIEW
_PLAN_MODE_ADDENDUM = "\n\n" + _prompts.MODE_PLAN


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
_MUTATING_TOOLS = frozenset({"shell_exec", "write_file"})


def _successful_write_paths(tool_results: tuple[ToolExecuted, ...]) -> list[str]:
    """Return the paths from every successful `write_file` tool call in this
    turn. Used by `code_with_retry` to treat write_file calls as first-class
    edits — same test/rollback cycle as SEARCH/REPLACE patches.
    """
    paths: list[str] = []
    for r in tool_results:
        if r.call.name != "write_file" or not r.result.ok:
            continue
        try:
            args = json.loads(r.call.body)
            path = args.get("path", "")
            if path and path not in paths:
                paths.append(path)
        except (json.JSONDecodeError, KeyError, AttributeError):
            pass
    return paths


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


def _parse_task_skills(task: Task) -> list[str]:
    """Extract the `Skills:` comma-separated list from a task body.

    Returns an empty list when the field is missing, "none", or only
    contains placeholder text. Same parsing posture as `_parse_task_files`.
    """
    for raw_line in task.body.splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("skills:"):
            continue
        rest = line[len("skills:") :].strip()
        if not rest or rest.lower() in ("none", "n/a", "-"):
            return []
        items: list[str] = []
        for chunk in rest.split(","):
            name = chunk.strip()
            if not name or name.startswith("<") or name.endswith(">"):
                continue
            items.append(name)
        return items
    return []


def _parse_task_files(task: Task) -> list[str]:
    """Extract the comma-separated `Files:` list from a task body.

    Empty list when the field is missing or the user wrote "n/a". A path
    ending in `/` is treated as a directory marker — the verifier checks
    `is_dir`, not `is_file`. Anything that looks like a description in
    angle brackets (placeholder from an unfilled template) is skipped.
    """
    for raw_line in task.body.splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("files:"):
            continue
        rest = line[len("files:") :].strip()
        if not rest or rest.lower() in ("n/a", "none", "-"):
            return []
        items: list[str] = []
        for chunk in rest.split(","):
            p = chunk.strip()
            if not p or p.startswith("<") or p.endswith(">"):
                continue
            items.append(p)
        return items
    return []


def _parse_task_test_command(task: Task) -> str | None:
    """Extract `Test command:` from a task body. Returns None for missing /
    "manual" / placeholder values — those mean "no machine verification"."""
    for raw_line in task.body.splitlines():
        line = raw_line.strip()
        if not line.lower().startswith("test command:"):
            continue
        cmd = line[len("test command:") :].strip()
        cmd = cmd.strip("`").strip()
        if not cmd or cmd.lower() in ("manual", "n/a", "none", "-"):
            return None
        if cmd.startswith("<") or cmd.endswith(">"):
            return None
        return cmd
    return None


def _verify_task_files(task: Task, cwd: Path) -> tuple[bool, str]:
    """Check every path in the task's `Files:` list exists on disk.

    Returns (ok, error). A path ending in `/` must be a directory; any
    other path must be a file. Missing entries are reported by name so
    the caller (run_plan) can re-prompt the model with a precise list."""
    files = _parse_task_files(task)
    if not files:
        return True, ""
    missing: list[str] = []
    for p in files:
        target = cwd / p.rstrip("/")
        if p.endswith("/"):
            if not target.is_dir():
                missing.append(p)
        else:
            if not target.is_file():
                missing.append(p)
    if missing:
        return False, ", ".join(missing)
    return True, ""


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
        shell_calls = [r for r in step_result.tool_results if r.call.name in _MUTATING_TOOLS]
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
        # Skill names currently loaded into context. `load_skill` adds,
        # `unload_skill` removes; the system prompt's skills addendum is
        # rebuilt from this set on every turn. Lazy by design — the model
        # decides what stack knowledge it needs and pays the token cost
        # only for what's loaded.
        self._loaded_skills: set[str] = set()

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
                # No SEARCH/REPLACE patch. The model may have written files
                # via the `write_file` tool instead — that's a first-class
                # path now, equal to SEARCH/REPLACE. Treat successful
                # write_file calls as the "edits" of this iteration: snapshot
                # is already captured below (lazy on first sight of each
                # path), tests run via the standard branch, rollback on
                # failure works because the snapshot is keyed by path.
                write_paths = _successful_write_paths(result.tool_results)
                if write_paths:
                    # Synthesize a no-op snapshot record so rollback works.
                    # The file's already been written by the tool dispatcher;
                    # we only need the pre-loop ORIGINAL captured BEFORE the
                    # tool fired — which means snapshotting now sees the
                    # already-written content (wrong). For greenfield this is
                    # fine — `original is None` and rollback unlinks. For
                    # overwrites we'd need a pre-write snapshot; that's a
                    # known limitation and the TODO below tracks it.
                    for p in write_paths:
                        target = self._cwd / p
                        if target not in pre_loop_snapshot:
                            # Best we can do: mark as "did not exist". For an
                            # overwrite of an existing file this leaks the
                            # ORIGINAL content on rollback — but write_file is
                            # primarily for greenfield, where this is correct.
                            pre_loop_snapshot[target] = None
                    test_output, tests_passed = await self._run_tests()
                    synthetic_edits = tuple(
                        Edit(path=p, search="", replace="") for p in write_paths
                    )
                    attempts.append(
                        PatchAttempt(
                            edits=synthetic_edits,
                            apply_ok=True,
                            apply_error="",
                            test_output=test_output,
                            tests_passed=tests_passed,
                        )
                    )
                    if tests_passed:
                        return StepResult(
                            reply=result.reply,
                            edits=[],
                            response=result.response,
                            attempts=tuple(attempts),
                            tool_results=result.tool_results,
                        )
                    if i == max_retries:
                        break
                    prompt = _TESTS_FAILED_PROMPT.format(output=test_output)
                    continue
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

        # Exhausted retries. Roll BACK to pre-loop state for files that
        # existed before — those got mutated by SEARCH/REPLACE and the
        # final state is half-applied junk. Files that DID NOT exist
        # before (snapshot stored as `None`) we LEAVE on disk: the model
        # wrote them via write_file as net-new artifacts; deleting them
        # loses the user's visible progress (Probe 2026-05-13: model
        # built setup.py + main.py + tests/ over several turns, then the
        # final retry failed, and we wiped the whole tree).
        for target, original in pre_loop_snapshot.items():
            if original is None:
                continue  # net-new file → keep it
            try:
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

        # Ensure git repo exists BEFORE the loop so every task can land in
        # its own commit. Missing → `git init` + a starter `.gitignore`
        # (covers venvs, build artifacts, pyc cache — common enough to be
        # universal). Pre-existing repo: untouched. Gated on `auto_git`
        # so tests / hermetic callers can keep the loop free of shell
        # side-effects.
        if self._config.agent.auto_git:
            await self._ensure_git_repo()

        # If the plan has no `Skills:` annotations, fire a single LLM
        # pass to add them. Cheap and one-shot; the result is written
        # back to TASKS.md so subsequent runs (and the user) see the
        # decision. `/annotate` can re-run this explicitly later.
        if self._config.agent.auto_annotate_plan and not any(_parse_task_skills(t) for t in tasks):
            # Surface the annotation pass to the user — it's an extra
            # LLM call before the loop starts, and silently spending
            # seconds on it would look like the agent froze.
            if on_tool_executed is not None:
                start_call = ToolCall(name="annotate_plan", body="{}")
                with suppress(Exception):
                    on_tool_executed(
                        start_call,
                        ToolResult(
                            start_call,
                            output="Annotating plan with skills (1 LLM pass)…",
                            ok=True,
                        ),
                    )
            new_text = await self._annotate_plan_with_skills(original_text)
            if new_text and new_text != original_text:
                _atomic_write(tasks_path, new_text)
                original_text = new_text
                initial_hash = _hash_text(new_text)
                tasks = parse_tasks_md(new_text)
                if on_tool_executed is not None:
                    done_call = ToolCall(name="annotate_plan", body="{}")
                    # Surface what got picked, per task — one line each
                    # so the user can scan it without reopening TASKS.md.
                    lines = ["Plan annotated. Skills per task:"]
                    for t in tasks:
                        s = _parse_task_skills(t)
                        lines.append(f"  {t.id}: {', '.join(s) if s else 'none'}")
                    with suppress(Exception):
                        on_tool_executed(
                            done_call,
                            ToolResult(done_call, output="\n".join(lines), ok=True),
                        )
            elif on_tool_executed is not None:
                fail_call = ToolCall(name="annotate_plan", body="{}")
                with suppress(Exception):
                    on_tool_executed(
                        fail_call,
                        ToolResult(
                            fail_call,
                            output="Annotation pass returned no changes — "
                            "running plan without auto-loaded skills.",
                            ok=False,
                        ),
                    )

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

            # Snapshot HEAD before the task — at task end we compare so
            # we can tell whether the model actually committed. `None`
            # before-the-first-commit is fine: any non-None after means
            # a commit happened. Skipped when auto_git is off.
            head_before: str | None = None
            if self._config.agent.auto_git:
                head_before = await self._git_head_sha()

            # Load the task's declared skills before code_with_retry —
            # so the per-task `_initial_messages` system prompt includes
            # the right stack guidance. Each new load fires through
            # `on_tool_executed` for the chat card.
            await self._load_skills_for_task(task, on_tool_executed)

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
            # Plan-level verification — defends against the model marking a
            # task done after only partly executing it. Three machine-
            # verifiable conditions:
            #   1. `Files:` — every listed path must exist on disk.
            #      Catches "model only made the folder, not setup.py".
            #   2. `Test command:` — must exit 0. Catches "files exist but
            #      logic is wrong". Skipped for "manual" / N/A / "pytest"
            #      (pipeline already ran pytest via `_run_tests`).
            #   3. Git HEAD advanced — the model is required by the
            #      checklist to commit at the end of each task. If HEAD
            #      didn't change, the model skipped that step.
            if outcome.status == "done":
                files_ok, _missing = _verify_task_files(task, self._cwd)
                if not files_ok:
                    outcome = TaskOutcome(
                        task=task,
                        step_result=step_result,
                        status="failed",
                    )
                else:
                    cmd = _parse_task_test_command(task)
                    # Skip plain `pytest` invocations — `_run_tests`
                    # already covered that, no point re-spawning it.
                    if cmd and cmd.strip() != "pytest":
                        verify_ok = await self._verify_task_test_command(cmd)
                        if not verify_ok:
                            outcome = TaskOutcome(
                                task=task,
                                step_result=step_result,
                                status="failed",
                            )
                if outcome.status == "done" and self._config.agent.auto_git:
                    head_after = await self._git_head_sha()
                    if head_after is None or head_after == head_before:
                        # No commit landed during the task. Mark failed
                        # so the plan halts and the user notices.
                        outcome = TaskOutcome(
                            task=task,
                            step_result=step_result,
                            status="failed",
                        )

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
                # "skipped" — model produced no patch and no write_file.
                # That's the model giving up; stop the plan so the user
                # sees what happened instead of silently rolling through
                # to the next task on top of an unfinished one.
                stopped_reason = "task_not_done"
                break

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

    async def _verify_task_test_command(self, command: str) -> bool:
        """Run the task's planner-declared `Test command` and return its
        exit-code-as-bool. Bypasses the model — we don't trust the model's
        own claim of success; we execute the command independently.

        Goes through `shell_exec` with `yolo` trust because this is plan-
        owned verification: the user explicitly authored the command in
        TASKS.md and accepted the plan, so it's not a model-injected
        command that needs the skeptic confirmation gate.
        """
        call = ToolCall(name="shell_exec", body=json.dumps({"command": command}))
        result = await execute(
            call,
            self._cwd,
            max_lines=self._config.agent.max_file_lines,
            runner=self._shell_runner,
            trust="yolo",
            shell_exec_timeout=self._config.agent.shell_exec_timeout,
            sandbox=self._config.agent.sandbox,
        )
        return result.ok

    async def _run_plan_shell(self, command: str) -> tuple[str, bool]:
        """Run a plan-owned shell command (`git init`, `git commit`, etc.).
        Bypasses skeptic confirmation because these are autonomous-plan
        operations the user already accepted by hitting /go; the command
        text comes from this module, not from the model. Best-effort: any
        error is captured in the returned (output, ok) pair so the caller
        can log but the plan loop keeps moving."""
        call = ToolCall(name="shell_exec", body=json.dumps({"command": command}))
        result = await execute(
            call,
            self._cwd,
            max_lines=self._config.agent.max_file_lines,
            runner=self._shell_runner,
            trust="yolo",
            shell_exec_timeout=self._config.agent.shell_exec_timeout,
            sandbox=self._config.agent.sandbox,
        )
        return result.output, result.ok

    async def _ensure_git_repo(self) -> None:
        """Initialise a git repo + starter `.gitignore` if neither exists.

        Idempotent: existing `.git` is left alone (including its config),
        existing `.gitignore` is appended to only if our markers are not
        already present. Failure here doesn't stop the plan — the loop
        will just run without commits.
        """
        if (self._cwd / ".git").exists():
            return
        await self._run_plan_shell("git init -q")
        # Best-effort author so the very first commit doesn't blow up on
        # a fresh dev machine without a global user.email. We only set
        # LOCAL config (this repo only) — global settings are the user's.
        await self._run_plan_shell(
            "git config user.email scalpel@local && git config user.name 'code-scalpel'"
        )
        gitignore = self._cwd / ".gitignore"
        starter = "\n".join(
            [
                "# Added by code-scalpel auto-init",
                ".venv/",
                "venv/",
                "__pycache__/",
                "*.pyc",
                ".pytest_cache/",
                ".mypy_cache/",
                ".ruff_cache/",
                "dist/",
                "build/",
                "*.egg-info/",
                "node_modules/",
                ".env",
                "",
            ]
        )
        if not gitignore.exists():
            with suppress(OSError):
                gitignore.write_text(starter)
        elif "code-scalpel auto-init" not in gitignore.read_text():
            with suppress(OSError), gitignore.open("a") as f:
                f.write("\n" + starter)

    async def _annotate_plan_with_skills(self, plan_text: str) -> str:
        """Run a single LLM pass that appends `Skills:` lines to each task.

        Builds a tight, focused prompt: the plan + the skill catalog + an
        OPTIONAL "Detected stack" hint listing filesystem-detected skills
        (only when the project has marker files — greenfield projects
        send no hint). Returns the rewritten plan; on any error returns
        the original text unchanged (best-effort, never breaks /go).
        """
        from code_scalpel.skills import active_skills, all_skills

        try:
            catalog_lines = [f"- {s.name}: {s.description}" for s in all_skills()]
            catalog = "\n".join(catalog_lines)
            detected = [s.name for s in active_skills(self._cwd)]
            if detected:
                detected_block = (
                    f"\nDetected stack in this project (filesystem hint, informational only): "
                    f"{', '.join(detected)}\n"
                )
            else:
                detected_block = (
                    "\nProject is empty / greenfield — no stack markers on disk. "
                    "You'll be building from scratch; pick skills based on the "
                    "files the plan asks you to create.\n"
                )
            user_msg = _prompts.ANNOTATE_SKILLS.format(plan=plan_text, catalog=catalog)
            user_msg += detected_block
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": _prompts.SYSTEM},
                {"role": "user", "content": user_msg},
            ]
            profile = self._config.current_profile
            response = await self._llm.chat(messages, **profile.inference_kwargs("ask"))
        except Exception:
            return plan_text
        reply = (response.content or "").strip()
        if not reply:
            return plan_text
        # The model sometimes wraps Markdown in a fence; strip that.
        if reply.startswith("```"):
            lines = reply.splitlines()
            if lines:
                lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                reply = "\n".join(lines)
        if "## T" not in reply:
            return plan_text  # model didn't follow format; keep original
        return reply

    async def _load_skills_for_task(
        self,
        task: Task,
        on_tool_executed: Callable[[ToolCall, ToolResult], None] | None,
    ) -> None:
        """Activate every skill listed in this task's `Skills:` line.

        Skills already in `_loaded_skills` are skipped (no chat spam for
        repeats). Each new load fires `on_tool_executed` with a synthetic
        load_skill call so the user sees the activation as a card.
        """
        from code_scalpel.skills import get_skill

        for name in _parse_task_skills(task):
            if name in self._loaded_skills:
                continue
            skill = get_skill(name)
            if skill is None:
                continue
            self._loaded_skills.add(name)
            if on_tool_executed is None:
                continue
            instr = skill.model_instructions()
            # Synthetic tool name `auto_load_skill` distinguishes the
            # plan-runner's auto-load from a model-initiated `load_skill`
            # in the chat (different card header). Not in TOOL_SCHEMAS —
            # the model can't call this name.
            call_view = ToolCall(name="auto_load_skill", body=json.dumps({"name": name}))
            output = (
                f"Skill '{name}' loaded (from plan annotation).\n\n{instr}"
                if instr
                else f"Skill '{name}' loaded (from plan annotation)."
            )
            with suppress(Exception):
                on_tool_executed(call_view, ToolResult(call_view, output=output, ok=True))

    async def annotate_plan(self) -> bool:
        """Public entry-point for `/annotate`. Reads TASKS.md, runs the
        skill-annotation pass, writes the result back. Returns True if
        the file changed, False otherwise (no plan, or annotator
        returned identical text)."""
        tasks_path = self._cwd / ".code-scalpel" / "TASKS.md"
        if not tasks_path.is_file():
            return False
        original = tasks_path.read_text()
        if not original.strip():
            return False
        new_text = await self._annotate_plan_with_skills(original)
        if not new_text or new_text == original:
            return False
        _atomic_write(tasks_path, new_text)
        return True

    async def _git_head_sha(self) -> str | None:
        """Return the current HEAD sha, or None if there isn't one yet
        (fresh repo, pre-first-commit state, or shell error).

        Used by `run_plan` to snapshot HEAD before each task and compare
        after, so we can detect whether the model actually committed.
        """
        out, ok = await self._run_plan_shell("git rev-parse HEAD 2>/dev/null")
        if not ok:
            return None
        # Output format: `exit code: 0\n---\n<sha>\n`.
        for line in out.splitlines():
            line = line.strip()
            if line and len(line) >= 7 and all(c in "0123456789abcdef" for c in line):
                return line
        return None

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
            # Normalize JSON whitespace so the model can't escape loop
            # detection by re-emitting `{"path": "x"}` vs `{"path":"x"}`.
            args_key = tc.arguments
            try:
                parsed = json.loads(tc.arguments) if tc.arguments else {}
                args_key = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
            except (json.JSONDecodeError, TypeError):
                pass
            key = (tc.name, args_key)
            if key in seen:
                looped = True
            seen.add(key)
        return looped

    async def _execute_native(self, tc: NativeToolCall) -> ToolResult:
        call = ToolCall(name=tc.name, body=tc.arguments)
        # Skill load/unload need agent state — handle them here before
        # falling through to the stateless tools dispatcher.
        if tc.name == "load_skill":
            return self._tool_load_skill(call)
        if tc.name == "unload_skill":
            return self._tool_unload_skill(call)
        return await execute(
            call,
            self._cwd,
            max_lines=self._config.agent.max_file_lines,
            runner=self._shell_runner,
            trust=self._config.agent.trust,
            shell_exec_timeout=self._config.agent.shell_exec_timeout,
            confirm_shell_exec=self._confirm_shell_exec,
            sandbox=self._config.agent.sandbox,
        )

    def _tool_schemas(self) -> list[dict[str, Any]]:
        """Build the tool list per request. `shell_exec` now ships at
        all three trust levels — skeptic gates each call through the
        confirmation callback registered at construction time (the
        TUI provides one; headless callers like probe/bench leave it
        `None` and shell_exec refuses in skeptic)."""
        return [*TOOL_SCHEMAS, SHELL_EXEC_SCHEMA, LOAD_SKILL_SCHEMA, UNLOAD_SKILL_SCHEMA]

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
        system = _SYSTEM_PROMPT + self._skills_catalog()
        if mode == "plan":
            system += _PLAN_MODE_ADDENDUM
        elif mode == "review":
            system += _REVIEW_MODE_ADDENDUM
        elif mode == "code":
            system += _CODE_MODE_ADDENDUM
        # Loaded-skills block goes after mode addenda so per-stack rules
        # win against generic mode guidance when they overlap (e.g. test
        # command preference). Always emitted — the model can load_skill
        # from any mode, not just code.
        system += self._skills_addendum()
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]
        # History may carry internal bookkeeping fields (`_tool_name`,
        # `_tool_args`) on tool messages for the compression pass. Strip
        # underscore-prefixed keys before handing the list to the LLM —
        # OpenAI-compat backends reject unknown fields on `tool` role.
        for entry in self._history:
            msgs.append({k: v for k, v in entry.items() if not k.startswith("_")})
        msgs.append({"role": "user", "content": user_msg})
        return msgs

    def _skills_catalog(self) -> str:
        """One-line-per-skill catalog of everything the model can load_skill.

        Always emitted into the system prompt so the model knows what's
        on the menu without having to discover. Cheap (~10 tokens per
        skill) and stable across turns.
        """
        from code_scalpel.skills import all_skills

        try:
            skills = all_skills()
        except Exception:
            return ""
        if not skills:
            return ""
        lines = [
            "",
            "",
            "Available skills (call load_skill('<name>') to add stack-specific guidance to your context):",
        ]
        for s in skills:
            lines.append(f"- {s.name}: {s.description}")
        return "\n".join(lines)

    def _skills_addendum(self) -> str:
        """Instructions block for currently loaded skills.

        Built from `self._loaded_skills` — what the model (or auto-load
        at plan start) has explicitly activated. Empty when nothing is
        loaded, so the cost is paid only for skills the agent decided
        it needs.
        """
        if not self._loaded_skills:
            return ""
        from code_scalpel.skills import get_skill

        blocks: list[str] = []
        for name in sorted(self._loaded_skills):
            skill = get_skill(name)
            if skill is None:
                continue
            instr = skill.model_instructions()
            if instr:
                blocks.append(instr)
        if not blocks:
            return ""
        return "\n\n" + "\n\n".join(blocks)

    def _tool_load_skill(self, call: ToolCall) -> ToolResult:
        """Intercept `load_skill` — add to `_loaded_skills`, return the
        skill's model_instructions so they're visible in the tool result
        chain too (the next turn's system prompt also carries them via
        `_skills_addendum`; the tool result is what the model sees
        immediately, for the current turn's reasoning)."""
        from code_scalpel.skills import get_skill

        args = self._decode_skill_args(call.body)
        name = str(args.get("name", "")).strip()
        if not name:
            return ToolResult(call, output="error: missing skill name", ok=False)
        skill = get_skill(name)
        if skill is None:
            return ToolResult(call, output=f"error: unknown skill {name!r}", ok=False)
        if name in self._loaded_skills:
            # Idempotent — don't re-inject the instructions block when the
            # plan-runner already loaded the skill for this task.
            return ToolResult(call, output=f"Skill '{name}' is already loaded.", ok=True)
        self._loaded_skills.add(name)
        instr = skill.model_instructions()
        if instr:
            return ToolResult(call, output=f"Skill '{name}' loaded.\n\n{instr}", ok=True)
        return ToolResult(call, output=f"Skill '{name}' loaded (no extra guidance).", ok=True)

    def _tool_unload_skill(self, call: ToolCall) -> ToolResult:
        args = self._decode_skill_args(call.body)
        name = str(args.get("name", "")).strip()
        if not name:
            return ToolResult(call, output="error: missing skill name", ok=False)
        if name not in self._loaded_skills:
            return ToolResult(call, output=f"Skill '{name}' was not loaded.", ok=False)
        self._loaded_skills.discard(name)
        return ToolResult(call, output=f"Skill '{name}' unloaded.", ok=True)

    @staticmethod
    def _decode_skill_args(body: str) -> dict[str, Any]:
        """Tolerate JSON-args (native function calling) or bare string
        (legacy <TOOL> form). Mirrors `_decode_args` in agent_tools."""
        body = body.strip()
        if not body:
            return {}
        if body.startswith("{"):
            try:
                obj = json.loads(body)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        return {"name": body}

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

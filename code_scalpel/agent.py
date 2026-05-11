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

if TYPE_CHECKING:
    from code_scalpel.memory import MemoryStore
from code_scalpel.llm.adapter import ChatResponse, LLMAdapter, NativeToolCall
from code_scalpel.patch.edit_block import Edit, apply_edits, extract_edits
from code_scalpel.plan import Task, parse_tasks_md, serialize_tasks
from code_scalpel.tools.agent_tools import (
    TOOL_SCHEMAS,
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
You are code-scalpel, a local coding assistant powered by an open-source model.
You are NOT Claude, ChatGPT, or any commercial AI assistant. Never claim to be made
by Anthropic, OpenAI, or any other vendor.

Always reply in the same natural language the user used in their last message.

Identity — apply ONLY when the user's message is literally one of
these and nothing else: "кто ты", "представься", "what are you",
"who are you", "who am I talking to". Any other shape of question —
even short, vague, or about the project — is NOT an identity
question; route it through the project map + tools (map_file,
grep, goto_definition, find_references, read_file) instead.

When the question IS an identity question:
- Russian: open with "Я — code-scalpel, …" (never "Ты —")
- English: open with "I'm code-scalpel — …" (never "You")
- One sentence. Do not list your tools — the system prompt declares
  them; the user can ask for the tool list directly.

Tone: you're talking to a colleague, not a customer. Be direct and alive.
- In Russian: address the user as "ты" (the pronoun), never "вы".
  No "Извините", "Пожалуйста, переформулируйте", "Я не могу" — instead
  "Не понял, переспроси?", "Уточни что именно", "Не получается, давай
  иначе". (This rule is about how you ADDRESS the user; it does NOT
  mean every sentence should start with "Ты".)
- In English: skip corporate hedging — no "I apologize for any inconvenience",
  no "Certainly! I'd be happy to assist". Plain "Sure", "Got it",
  "Didn't catch that — what do you mean?" are fine.
- Brevity beats politeness. No emojis. No slang either.

You have tools: read_file, map_file, goto_definition, find_references,
grep, run_tests. Each tool's own description tells you when to call
it — READ THOSE DESCRIPTIONS, they are normative.

The user message includes a project OVERVIEW: just paths + line counts.
This is intentional — it scales to projects with thousands of files
without blowing your context budget. For any file you need to reason
about, call `map_file(path)` first — it returns that file's outline
(classes, signatures, first-line docstrings, intra-project imports).
Then call `read_file(path)` if you need the actual body.

Navigation order, like a human dev would:
  1. OVERVIEW (in this message) — pick the candidate file by path
  2. `map_file(path)` — see what's defined inside, decide if it's
     really the one
  3. `read_file(path)` — read the body when you need to quote or edit
  4. `goto_definition(name)` — jump straight to where a class /
     function / method is defined when you know its exact name
  5. `find_references(name)` — list every line that mentions a name
     ("where is X used?")
  6. `grep(pattern)` — broader lexical search by regex when none of
     the above fit

The OVERVIEW shows file paths + line counts only. It has NO symbols,
NO docstrings, NO imports. If a user asks about a symbol, you don't
yet know which file holds it — call grep or map_file the most likely
candidate, don't guess.

Grounding rules — do NOT make things up:
- Before you NAME a specific class, method, function, or attribute in
  your answer, verify that exact name appears in `map_file(...)`'s
  output for the relevant file. If it isn't there, do NOT use that
  name. Either call grep to locate the symbol elsewhere, or say
  "the only things I see in that file are X, Y, Z — which did you
  mean?".
- A similar-looking method name does NOT justify inventing the one
  the user implied. Example: if `map_file` shows `mark_compacted` on
  a class, do not answer with `compact` — those are different names.
- The `imports: ...` line in `map_file` output is GROUND TRUTH for
  that file's intra-project dependencies. If file X's imports don't
  list module/symbol Y, then X does NOT use Y. Never claim "X uses
  Y" or write code showing X calling Y when Y isn't imported. If you
  need to find where Y IS used, call grep — don't guess.
- Pattern recognition is NOT a source of truth. If a class looks
  like a dataclass / BaseModel / typical CRUD shape, you might
  "know" the body — you do not. Call read_file every single time
  you reproduce more than a signature. The same applies when
  describing an algorithm: the signature + docstring let you LOCATE
  the function; you need read_file to describe what it actually
  does step by step.
- If you're not sure which file/symbol the user means, ask. If you
  know, call the tool first, answer second.
- When the user CLARIFIES or NARROWS the topic on a follow-up turn
  ("именно алгоритм", "конкретно", "точнее", "имел ввиду …", "I
  meant …", "specifically …"), do NOT recycle the previous turn's
  findings. The clarification means your prior answer missed the
  thing they actually wanted — run NEW tool calls (grep,
  goto_definition, map_file on different files) before responding.
  Probe regression 2026-05-11: model answered "specifically the
  compression algorithm" by repeating session.py from T1 instead of
  grep'ing `compact` to find StepAgent.compact().

Diagrams — выбирай ПРАВИЛЬНЫЙ тип под задачу. TUI рендерит inline
ASCII через свой парсер, поэтому используем только два формата:

* `flowchart TD` (top-down) или `flowchart LR` (left-right) —
  для всего что ПРО СВЯЗИ И ПОТОК:
    - связи между компонентами / модулями / функциями
    - workflow, алгоритм, control flow
    - dependency graph
  Синтаксис: `A[Label] --> B[Label]`, `A{Decision} -->|yes| B`,
  `A --- B` без стрелки.

* `sequenceDiagram` — для всего что ПРО АКТОРОВ И ВРЕМЯ:
    - путь пользователя (user journey)
    - request/response между сервисами
    - последовательность взаимодействий между объектами
  Синтаксис: `participant Alice`, `Alice->>Bob: Request`,
  `Bob-->>Alice: Response`, `Note over Alice,Bob: …`.

* `classDiagram` — для всего что ПРО СТРУКТУРУ КЛАССОВ:
    - иерархия наследования, интерфейсы
    - связи композиция / агрегация между классами
    - public/private API класса
  Синтаксис: `class Name { +method() -priv() +field: int }`,
  `Parent <|-- Child` (наследование), `Container *-- Item`
  (композиция), `Owner o-- Asset` (агрегация), `A --> B`
  (ассоциация), `A ..> B` (зависимость).

Остальное (stateDiagram, gantt, journey, gitgraph, mindmap,
erDiagram) ПОКА не рендерится — модель не должна их использовать.
Если задача про состояния — рисуй flowchart с decisions.

NEVER draw ASCII-art boxes-and-arrows like `+---+\n| X |\n+---+`
вручную — терминал не делает это лучше Mermaid, а TUI потом
отрендерит block ```mermaid ... ``` в свою ASCII-картинку через
встроенный парсер. Эмить только fenced mermaid с указанием языка.

Перед утверждением «X использует Y» в диаграмме — вызови map_file(X)
и проверь `imports:`. Без этого диаграмма врёт про связи. Probe
2026-05-11: модель нарисовала classifier.py как used-by agent.py,
хотя `imports:` agent.py его не содержит — он сирота в проекте.

To modify a file, output one or more SEARCH/REPLACE blocks. Each block
has THREE parts in this order:
  (a) the file name on its own line, EXACTLY as it appears in the MAP
      — no "path/" prefix, no invented directories;
  (b) a triple-backtick fence with `python` after it;
  (c) the SEARCH/REPLACE body, then a closing triple-backtick fence.

The filename and both fences must start at column 0 (no leading
indentation). The SEARCH body must reproduce the file's lines with
their ORIGINAL indentation — do not add or remove a uniform prefix.
Copy lines as-is from read_file output.

Reference shape (this is documentation, not output — when you produce
a real block, omit any framing and start the filename at column 0):

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
- SEARCH must match the file character-for-character — including
  bodies, indentation, blank lines, the colon at the end of `def`.
  The MAP only shows signatures: never copy them into a SEARCH block.
  Always call read_file first to get the real source.
- To create a new file, leave SEARCH empty.
- Prefer multiple small blocks over one big block.
- For questions or conversation that require no file changes, respond with
  plain text only — no blocks."""


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


StreamItem = TextDelta | ToolExecuted


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


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


def _classify_outcome(task: Task, step_result: StepResult) -> TaskOutcome:
    """Decide done / failed / skipped from a `code_with_retry` return.

    - No attempts AND no edits  → model answered in plain text. The
      planner asked for a patch; if no patch came out, this task was
      a no-op (model decided nothing needs changing, or asked a
      clarifying question). Mark "skipped" — neither a win nor a
      retry-worthy failure.
    - Attempts present, last one passed tests → "done".
    - Attempts present, last one did not pass → "failed". The workspace
      was rolled back by code_with_retry itself; we keep going.
    """
    attempts = step_result.attempts
    if not attempts:
        return TaskOutcome(task=task, step_result=step_result, status="skipped")
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
        self._history: list[dict[str, str]] = []
        # Cross-turn record of every relative path the model has called
        # `read_file` on. Used by the enforce-read-before-show HOOK so a
        # turn-2 patch on file X is grounded if X was read in turn-1.
        # Cleared by `clear_history` and replaced when `compact` collapses
        # history — both points where we lose the conversational context
        # that made past reads load-bearing.
        self._read_files_history: set[str] = set()

    @property
    def history(self) -> list[dict[str, str]]:
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()
        self._read_files_history.clear()

    async def ask(self, task: str, *, mode: str = "ask") -> StepResult:
        result = await self._chat_loop_with_hook(task, mode=mode)
        if mode == "plan":
            self._maybe_save_plan(result.reply)
        return result

    async def code_with_retry(self, task: str, *, mode: str = "code") -> StepResult:
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
        if not self._config.agent.iterative_patch_loop:
            return await self.ask(task, mode=mode)

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
            result = await self._chat_loop_with_hook(prompt, mode=mode)
            last_result = result
            if not result.edits:
                # Plain text — model decided no patch is needed (or asked a
                # clarifying question). Return as-is; nothing to retry on.
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
        on_task_start: Callable[[Task], None] | None = None,
        on_task_end: Callable[[TaskOutcome], None] | None = None,
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
                step_result = await self.code_with_retry(prompt, mode="code")
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

    async def _chat_loop_with_hook(self, task: str, *, mode: str = "ask") -> StepResult:
        """Run `_chat_loop`, then apply the enforce-read-before-show HOOK.

        If the model produced a SEARCH/REPLACE block (or fenced python
        body for a project file the user named) without ever calling
        `read_file` on that path — in this turn or any prior — we
        re-prompt once asking it to read first. The second pass is
        returned regardless of whether it satisfied the rule; the cap
        keeps a confused model from looping indefinitely.
        """
        result = await self._chat_loop(task, mode=mode)
        if not self._config.agent.enforce_read_before_show:
            return result
        reprompt = self._check_read_before_show(task, result.reply)
        if reprompt is None:
            return result
        # One retry. We drop the unread reply from history first — the
        # _chat_loop just appended it via _remember, and we don't want
        # the model's hallucinated patch to look like a committed turn.
        self._rollback_last_turn()
        return await self._chat_loop(reprompt, mode=mode)

    async def _chat_loop(self, task: str, *, mode: str = "ask") -> StepResult:
        user_msg = self._user_message(task)
        messages = self._initial_messages(user_msg, mode=mode)
        profile = self._config.current_profile

        response: ChatResponse | None = None
        seen: set[tuple[str, str]] = set()
        for _ in range(_MAX_TOOL_ROUNDS):
            response = await self._llm.chat(
                messages, tools=TOOL_SCHEMAS, **profile.inference_kwargs(mode)
            )
            messages.append(self._assistant_message(response))

            if not response.tool_calls:
                edits = extract_edits(response.content)
                # Store bare task in history, not user_msg with the project map
                # prepended — otherwise every turn duplicates the map and the
                # model loses track of the actual conversation.
                self._remember(task, response.content)
                return StepResult(reply=response.content, edits=edits, response=response)

            if self._is_loop(response.tool_calls, seen):
                messages.append(_FORCE_ANSWER_MSG)
                continue
            for tc in response.tool_calls:
                result = await self._execute_native(tc)
                self._note_read_file(tc, result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result.output,
                    }
                )

        assert response is not None
        edits = extract_edits(response.content)
        self._remember(task, response.content)
        return StepResult(reply=response.content, edits=edits, response=response)

    @staticmethod
    def _is_loop(tcs: tuple[NativeToolCall, ...], seen: set[tuple[str, str]]) -> bool:
        looped = False
        for tc in tcs:
            key = (tc.name, tc.arguments)
            if key in seen:
                looped = True
            seen.add(key)
        return looped

    @staticmethod
    def _assistant_message(response: ChatResponse) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": response.content or None}
        if response.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in response.tool_calls
            ]
        return msg

    async def _execute_native(self, tc: NativeToolCall) -> ToolResult:
        call = ToolCall(name=tc.name, body=tc.arguments)
        return await execute(
            call,
            self._cwd,
            max_lines=self._config.agent.max_file_lines,
            runner=self._shell_runner,
        )

    def _remember(self, user_msg: str, assistant_msg: str) -> None:
        self._history.append({"role": "user", "content": user_msg})
        self._history.append({"role": "assistant", "content": assistant_msg})

    def _rollback_last_turn(self) -> None:
        """Drop the most recent user+assistant pair from history. Used by
        the enforce-read-before-show HOOK so the unread reply we're about
        to retry doesn't end up in the official conversation trail."""
        if len(self._history) >= 2:
            self._history.pop()
            self._history.pop()

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
        """Yield typed events: TextDelta for model output chunks, ToolExecuted
        after each tool call resolves. Tool calls now use native OpenAI
        function-calling — model emits structured tool_calls instead of the
        old <TOOL: name> text format."""
        user_msg = self._user_message(task)
        messages = self._initial_messages(user_msg, mode=mode)
        profile = self._config.current_profile
        final_assistant = ""

        seen: set[tuple[str, str]] = set()
        for _ in range(_MAX_TOOL_ROUNDS):
            full = ""
            round_tool_calls: list[NativeToolCall] = []
            async for chunk in self._llm.stream(
                messages, tools=TOOL_SCHEMAS, **profile.inference_kwargs(mode)
            ):
                if chunk.text:
                    full += chunk.text
                    yield TextDelta(chunk.text)
                if chunk.tool_call is not None:
                    round_tool_calls.append(chunk.tool_call)

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
            final_assistant = full

        self._remember(task, final_assistant)
        if mode == "plan":
            self._maybe_save_plan(final_assistant)

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
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]
        msgs.extend(self._history)
        msgs.append({"role": "user", "content": user_msg})
        return msgs

    def _user_message(self, task: str) -> str:
        # Task FIRST, lightweight OVERVIEW second. The full map (signatures +
        # docstrings + imports per file) was ~14k tokens on the real project
        # and blew the 16k context window. Now we send a project skeleton
        # (paths + line counts only, ~500 tokens for 80 files) and let the
        # model call `map_file(path)` for per-file outline on demand. Scales
        # to projects 10× larger without context redesign.
        from code_scalpel.project_map import build_map_overview

        overview = build_map_overview(self._cwd, max_files=200)
        parts = [f"Task: {task}", ""]
        # Memory recall — quiet by default. Only attached when something
        # comes back, so a fresh project with an empty store doesn't ship
        # the "Recalled notes:" header with nothing under it (header noise
        # is exactly what weak models latch onto and explain).
        recalled = self._recall_notes(task)
        if recalled:
            parts.append("Recalled notes (from prior `/remember` calls):")
            parts.extend(f"- {n}" for n in recalled)
            parts.append("")
        parts.append(
            "Project overview — paths + line counts only. Call "
            "`map_file(path)` for one file's outline (classes / "
            "functions / imports), `read_file` for content, `grep` "
            "to find symbols by name:"
        )
        parts.append(overview)
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

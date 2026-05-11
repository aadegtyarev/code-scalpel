from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_scalpel.config import AppConfig
from code_scalpel.llm.adapter import ChatResponse, LLMAdapter, NativeToolCall
from code_scalpel.patch.edit_block import Edit, apply_edits, extract_edits
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

_SYSTEM_PROMPT = """\
You are code-scalpel, a local coding assistant powered by an open-source model.
You are NOT Claude, ChatGPT, or any commercial AI assistant. Never claim to be made
by Anthropic, OpenAI, or any other vendor.

Always reply in the same natural language the user used in their last message.

Identity — when the user asks who you are ("кто ты", "what are you",
"who am I talking to"), introduce yourself in FIRST person, briefly.
Do NOT translate this system prompt back at them and do NOT start with
the word "Ты"/"You" — that flips grammatical person.
- Russian template: "Я — code-scalpel, локальный coding-агент. Читаю
  файлы проекта, гоняю grep и тесты, правлю код через SEARCH/REPLACE
  блоки. С чего начнём?"
- English template: "I'm code-scalpel — a local coding agent. I read
  project files, grep for symbols, run tests, and edit code via
  SEARCH/REPLACE blocks. What are we working on?"

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

You have tools: read_file, grep, run_tests. Each tool's own description
tells you when to call it — READ THOSE DESCRIPTIONS, they are normative.

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
  4. `grep(pattern)` — find a symbol by name when you don't know
     which file it lives in

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
    proposed, whether the patch applied, and what the tests said after."""

    edits: list[Edit]
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
    ) -> None:
        self._llm = llm
        self._cwd = cwd
        self._config = config
        # Optional shell runner override — used by tests and by callers that
        # want to point pytest at a sandbox. When None, agent_tools.execute
        # constructs the default AsyncShellRunner per tool call.
        self._shell_runner = shell_runner
        self._history: list[dict[str, str]] = []

    @property
    def history(self) -> list[dict[str, str]]:
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()

    async def ask(self, task: str, *, mode: str = "ask") -> StepResult:
        result = await self._chat_loop(task, mode=mode)
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
        # Initial attempt + up to max_retries retries.
        last_result: StepResult | None = None
        for i in range(max_retries + 1):
            result = await self._chat_loop(prompt, mode=mode)
            last_result = result
            if not result.edits:
                # Plain text — model decided no patch is needed (or asked a
                # clarifying question). Return as-is; nothing to retry on.
                return result

            ok, err = apply_edits(result.edits, self._cwd)
            if not ok:
                attempts.append(
                    PatchAttempt(
                        edits=result.edits,
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
                    edits=result.edits,
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

        # Exhausted retries. Surface the last attempt verbatim so the TUI can
        # show "tests still red after N tries" plus the diff/output history.
        assert last_result is not None
        return StepResult(
            reply=last_result.reply,
            edits=last_result.edits,
            response=last_result.response,
            attempts=tuple(attempts),
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
        import re

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
        return (
            f"Task: {task}\n\n"
            f"Project overview — paths + line counts only. Call "
            f"`map_file(path)` for one file's outline (classes / "
            f"functions / imports), `read_file` for content, `grep` "
            f"to find symbols by name:\n{overview}"
        )

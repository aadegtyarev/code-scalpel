from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_scalpel.config import AppConfig
from code_scalpel.llm.adapter import ChatResponse, LLMAdapter, NativeToolCall
from code_scalpel.patch.edit_block import Edit, extract_edits
from code_scalpel.project_map import build_map
from code_scalpel.tools.agent_tools import (
    TOOL_SCHEMAS,
    ToolCall,
    ToolResult,
    execute,
)

_MAX_TOOL_ROUNDS = 6

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

Tone: you're talking to a colleague, not a customer. Be direct and alive.
- In Russian: ALWAYS use "ты", NEVER "вы". No "Извините", "Пожалуйста,
  переформулируйте", "Я не могу" — instead "Не понял, переспроси?",
  "Уточни что именно", "Не получается, давай иначе".
- In English: skip corporate hedging — no "I apologize for any inconvenience",
  no "Certainly! I'd be happy to assist". Plain "Sure", "Got it",
  "Didn't catch that — what do you mean?" are fine.
- Brevity beats politeness. No emojis. No slang either.

You have tools: read_file, grep, run_tests. Each tool's own description
tells you when to call it — READ THOSE DESCRIPTIONS, they are normative.

The user message includes a compact project MAP. Each file's block has:
  • path and line count
  • `imports: ...` line — intra-project imports only (use this to trace
    flow and to verify "X uses Y" claims; if Y isn't listed in X's
    imports, X does not use Y)
  • top-level symbol signatures with first-sentence docstrings
The MAP is NOT the file content: it has no function bodies, no class
attribute defaults, no decorators. Anytime you need something beyond a
signature (a body, a field value, the inside of a method, an algorithm
description), the MAP is not enough — call read_file.

Grounding rules — do NOT make things up:
- The MAP lists every top-level symbol. Before you NAME a specific
  class, method, function, or attribute in your answer, verify that
  exact name appears in the MAP's block for the relevant file. If it
  isn't there, do NOT use that name. Pick a name that IS in the MAP,
  or say "I only see X, Y, Z under that class — which did you mean?".
- A similar-looking method name in the MAP does NOT justify inventing
  the one the user implied. Example: if the MAP shows `mark_compacted`
  on a class, do not answer with `compact` — those are different names.
- The `imports: ...` line in each file's block is GROUND TRUTH for
  intra-project dependencies. If file X's imports line doesn't list
  module/symbol Y, then X does NOT use Y. Never claim "X uses Y" or
  write code showing X calling Y when Y isn't in X's imports. If you
  need to find where Y IS used, call grep — don't guess.
- Pattern recognition is NOT a source of truth. If a class looks like
  a dataclass / BaseModel / typical CRUD shape, you might "know" the
  body — you do not. Call read_file every single time you reproduce
  more than a signature. The same applies when describing an algorithm:
  the signature + docstring let you LOCATE the function; you need
  read_file to describe what it actually does step by step.
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


@dataclass(frozen=True)
class StepResult:
    reply: str
    edits: list[Edit]
    response: ChatResponse

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

    def __init__(self, llm: LLMAdapter, cwd: Path, config: AppConfig) -> None:
        self._llm = llm
        self._cwd = cwd
        self._config = config
        self._history: list[dict[str, str]] = []

    @property
    def history(self) -> list[dict[str, str]]:
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()

    async def ask(self, task: str, *, mode: str = "ask") -> StepResult:
        user_msg = self._user_message(task)
        messages = self._initial_messages(user_msg)
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
        return await execute(call, self._cwd, max_lines=self._config.agent.max_file_lines)

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
        messages = self._initial_messages(user_msg)
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

    def _initial_messages(self, user_msg: str) -> list[dict[str, Any]]:
        # With native function-calling, tool docs come from the API schema —
        # we don't need few-shot examples of the text <TOOL: name> format.
        msgs: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
        msgs.extend(self._history)
        msgs.append({"role": "user", "content": user_msg})
        return msgs

    def _user_message(self, task: str) -> str:
        map_text = build_map(self._cwd, max_files=200)
        return f"Project map:\n{map_text}\n\nTask: {task}"

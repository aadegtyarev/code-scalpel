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

You have tools available: read_file, grep, run_tests. Use them when you need
information. The user message includes a compact MAP of the project (paths +
top-level symbols) but NOT the full file content — call read_file before
editing a file you haven't yet inspected.

To modify a file, output one or more SEARCH/REPLACE blocks:

    path/from/the/map.py
    ```python
    <<<<<<< SEARCH
    <lines that currently exist in the file, EXACTLY>
    =======
    <lines that should replace them>
    >>>>>>> REPLACE
    ```

Rules:
- SEARCH must match the file character-for-character.
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

    async def ask(self, task: str) -> StepResult:
        user_msg = self._user_message(task)
        messages = self._initial_messages(user_msg)
        profile = self._config.current_profile

        response: ChatResponse | None = None
        seen: set[tuple[str, str]] = set()
        for _ in range(_MAX_TOOL_ROUNDS):
            response = await self._llm.chat(
                messages, tools=TOOL_SCHEMAS, **profile.inference_kwargs()
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
        response = await self._llm.chat(msgs, **profile.inference_kwargs())
        summary = response.content.strip()
        self._history = [
            {
                "role": "user",
                "content": f"Summary of the earlier session:\n{summary}",
            }
        ]
        return summary

    async def stream_ask(self, task: str) -> AsyncIterator[StreamItem]:
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
                messages, tools=TOOL_SCHEMAS, **profile.inference_kwargs()
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

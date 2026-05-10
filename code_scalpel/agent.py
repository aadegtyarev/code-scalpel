from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from code_scalpel.config import AppConfig
from code_scalpel.llm.adapter import ChatResponse, LLMAdapter
from code_scalpel.patch.edit_block import Edit, extract_edits
from code_scalpel.project_map import build_map
from code_scalpel.tools.agent_tools import (
    ToolCall,
    ToolResult,
    execute,
    format_result,
    parse_tool_calls,
)

_MAX_TOOL_ROUNDS = 6

_SYSTEM_PROMPT = """\
You are code-scalpel, a local coding assistant powered by an open-source model.
You are NOT Claude, ChatGPT, or any commercial AI assistant. Never claim to be made
by Anthropic, OpenAI, or any other vendor.

Always reply in the same natural language the user used in their last message.

You can read project files on demand. Pick a real path from the project map
(NOT the placeholder shown below):

    <TOOL: read_file>
    {actual path from the map}
    </TOOL>

The system will reply with a <RESULT: read_file> block containing the file
with line numbers. Always call read_file before editing a file you haven't
already inspected — the project map only shows symbols, not full content.

To modify a file, output one or more SEARCH/REPLACE blocks (path is also a
real path, not a placeholder):

    {actual path from the map}
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
  plain text only — no tools, no blocks."""

_FEW_SHOT_USER = """\
Project map:
mathutil.py [2L]
  def add(a, b)

Task: add type hints to add(). Use int."""

_FEW_SHOT_ASSISTANT_1 = """\
<TOOL: read_file>
mathutil.py
</TOOL>"""

_FEW_SHOT_USER_2 = """\
<RESULT: read_file>
path: mathutil.py
---
1  def add(a, b):
2      return a + b
</RESULT>"""

_FEW_SHOT_ASSISTANT_2 = """\
mathutil.py
```python
<<<<<<< SEARCH
def add(a, b):
    return a + b
=======
def add(a: int, b: int) -> int:
    return a + b
>>>>>>> REPLACE
```"""


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
        for _ in range(_MAX_TOOL_ROUNDS):
            response = await self._llm.chat(messages, **profile.inference_kwargs())
            messages.append({"role": "assistant", "content": response.content})

            calls = parse_tool_calls(response.content)
            if not calls:
                edits = extract_edits(response.content)
                self._remember(user_msg, response.content)
                return StepResult(reply=response.content, edits=edits, response=response)

            tool_msg = await self._run_tools(calls)
            messages.append({"role": "user", "content": tool_msg})

        assert response is not None
        edits = extract_edits(response.content)
        self._remember(user_msg, response.content)
        return StepResult(reply=response.content, edits=edits, response=response)

    def _remember(self, user_msg: str, assistant_msg: str) -> None:
        self._history.append({"role": "user", "content": user_msg})
        self._history.append({"role": "assistant", "content": assistant_msg})

    async def compact(self) -> str | None:
        """Summarize history into a short note and replace it. Returns summary
        text, or None if history is empty."""
        if not self._history:
            return None
        joined = "\n\n".join(
            f"[{m['role']}]\n{m['content']}" for m in self._history
        )
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
        after each tool call resolves. The TUI dispatches per-type."""
        user_msg = self._user_message(task)
        messages = self._initial_messages(user_msg)
        profile = self._config.current_profile
        final_assistant = ""

        for _ in range(_MAX_TOOL_ROUNDS):
            full = ""
            async for chunk in self._llm.stream(messages, **profile.inference_kwargs()):
                full += chunk
                yield TextDelta(chunk)
            messages.append({"role": "assistant", "content": full})

            calls = parse_tool_calls(full)
            if not calls:
                final_assistant = full
                break

            results: list[ToolResult] = []
            for call in calls:
                result = await execute(call, self._cwd, max_lines=self._config.agent.max_file_lines)
                results.append(result)
                yield ToolExecuted(call, result)
            tool_msg = "\n\n".join(format_result(r) for r in results)
            messages.append({"role": "user", "content": tool_msg})
            final_assistant = full

        self._remember(user_msg, final_assistant)

    async def _run_tools(self, calls: list[ToolCall]) -> str:
        rendered: list[str] = []
        for c in calls:
            result = await execute(c, self._cwd, max_lines=self._config.agent.max_file_lines)
            rendered.append(format_result(result))
        return "\n\n".join(rendered)

    def _initial_messages(self, user_msg: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _FEW_SHOT_USER},
            {"role": "assistant", "content": _FEW_SHOT_ASSISTANT_1},
            {"role": "user", "content": _FEW_SHOT_USER_2},
            {"role": "assistant", "content": _FEW_SHOT_ASSISTANT_2},
            *self._history,
            {"role": "user", "content": user_msg},
        ]

    def _user_message(self, task: str) -> str:
        map_text = build_map(self._cwd, max_files=200)
        return f"Project map:\n{map_text}\n\nTask: {task}"

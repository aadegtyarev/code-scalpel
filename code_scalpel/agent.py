from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from code_scalpel.config import AppConfig
from code_scalpel.llm.adapter import ChatResponse, LLMAdapter
from code_scalpel.patch.edit_block import Edit, extract_edits
from code_scalpel.project_map import build_map
from code_scalpel.tools.agent_tools import ToolCall, execute, format_result, parse_tool_calls

_MAX_TOOL_ROUNDS = 6

_SYSTEM_PROMPT = """\
You are code-scalpel, a local coding assistant powered by an open-source model.
You are NOT Claude, ChatGPT, or any commercial AI assistant. Never claim to be made
by Anthropic, OpenAI, or any other vendor.

Always reply in the same natural language the user used in their last message.

You can read project files on demand using this tool format:

    <TOOL: read_file>
    relative/path/to/file.py
    </TOOL>

The system will reply with:

    <RESULT: read_file>
    path: relative/path/to/file.py
    ---
    <file content with line numbers>
    </RESULT>

The user message contains a compact MAP of the project (paths + top-level
symbols) but NOT the full content. Before editing a file, call read_file to
see its current text.

To modify a file, output one or more SEARCH/REPLACE blocks. Format:

    path/to/file.py
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


class StepAgent:
    """Multi-turn agent: model can call read_file, then produces SEARCH/REPLACE."""

    def __init__(self, llm: LLMAdapter, cwd: Path, config: AppConfig) -> None:
        self._llm = llm
        self._cwd = cwd
        self._config = config

    async def ask(self, task: str) -> StepResult:
        messages = self._initial_messages(task)
        profile = self._config.current_profile

        response: ChatResponse | None = None
        for _ in range(_MAX_TOOL_ROUNDS):
            response = await self._llm.chat(messages, **profile.inference_kwargs())
            messages.append({"role": "assistant", "content": response.content})

            calls = parse_tool_calls(response.content)
            if not calls:
                edits = extract_edits(response.content)
                return StepResult(reply=response.content, edits=edits, response=response)

            tool_msg = await self._run_tools(calls)
            messages.append({"role": "user", "content": tool_msg})

        assert response is not None
        edits = extract_edits(response.content)
        return StepResult(reply=response.content, edits=edits, response=response)

    async def stream_ask(self, task: str) -> AsyncIterator[str]:
        """Stream the model's tokens. Tool calls execute mid-loop; results are
        yielded as text chunks so the TUI can render them inline."""
        messages = self._initial_messages(task)
        profile = self._config.current_profile

        for _ in range(_MAX_TOOL_ROUNDS):
            full = ""
            async for chunk in self._llm.stream(messages, **profile.inference_kwargs()):
                full += chunk
                yield chunk
            messages.append({"role": "assistant", "content": full})

            calls = parse_tool_calls(full)
            if not calls:
                return

            tool_msg = await self._run_tools(calls)
            yield f"\n\n{tool_msg}\n\n"
            messages.append({"role": "user", "content": tool_msg})

    async def _run_tools(self, calls: list[ToolCall]) -> str:
        rendered: list[str] = []
        for c in calls:
            result = await execute(c, self._cwd, max_lines=self._config.agent.max_file_lines)
            rendered.append(format_result(result))
        return "\n\n".join(rendered)

    def _initial_messages(self, task: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _FEW_SHOT_USER},
            {"role": "assistant", "content": _FEW_SHOT_ASSISTANT_1},
            {"role": "user", "content": _FEW_SHOT_USER_2},
            {"role": "assistant", "content": _FEW_SHOT_ASSISTANT_2},
            {"role": "user", "content": self._user_message(task)},
        ]

    def _user_message(self, task: str) -> str:
        map_text = build_map(self._cwd, max_files=200)
        return f"Project map:\n{map_text}\n\nTask: {task}"

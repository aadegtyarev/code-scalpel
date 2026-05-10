"""Tools the LLM can invoke during an agent turn.

Format (model emits in its response):

    <TOOL: read_file>
    path/to/file.py
    </TOOL>

Result (we feed back as the next user message):

    <RESULT: read_file>
    path: path/to/file.py
    ---
    <file content here>
    </RESULT>

The agent loops on this until the model produces a turn with no tool calls
(at which point we treat the message as final and look for SEARCH/REPLACE
blocks).

For v0.2 we ship one tool: `read_file`. `grep`, `list_files`, `run_tests`
are next.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from code_scalpel.tools.files import read_file

_TOOL_RE = re.compile(
    r"<TOOL:\s*(?P<name>\w+)\s*>\n"
    r"(?P<body>.*?)\n?"
    r"</TOOL>",
    re.DOTALL,
)


@dataclass(frozen=True)
class ToolCall:
    name: str
    body: str  # raw argument text — interpretation is per-tool


@dataclass(frozen=True)
class ToolResult:
    call: ToolCall
    output: str
    ok: bool


def parse_tool_calls(text: str) -> list[ToolCall]:
    """Extract all <TOOL: name> blocks from a model response."""
    return [
        ToolCall(name=m.group("name"), body=m.group("body").strip())
        for m in _TOOL_RE.finditer(text)
    ]


def format_result(result: ToolResult) -> str:
    """Render a tool result for the next user-message turn."""
    return f"<RESULT: {result.call.name}>\n{result.output}\n</RESULT>"


async def execute(call: ToolCall, cwd: Path, max_lines: int = 400) -> ToolResult:
    """Dispatch a tool call by name. Returns a ToolResult — never raises."""
    if call.name == "read_file":
        return _tool_read_file(call, cwd, max_lines=max_lines)
    return ToolResult(
        call=call,
        output=f"error: unknown tool {call.name!r}",
        ok=False,
    )


def _tool_read_file(call: ToolCall, cwd: Path, *, max_lines: int) -> ToolResult:
    path_str = call.body.strip()
    if not path_str:
        return ToolResult(call, output="error: missing file path", ok=False)
    # Reject absolute / parent-escaping paths
    if path_str.startswith("/") or ".." in Path(path_str).parts:
        return ToolResult(
            call, output=f"error: path must be inside the project: {path_str}", ok=False
        )
    path = cwd / path_str
    if not path.is_file():
        return ToolResult(call, output=f"error: file not found: {path_str}", ok=False)
    try:
        content = read_file(path, max_lines=max_lines)
    except OSError as e:
        return ToolResult(call, output=f"error: {e}", ok=False)
    return ToolResult(call, output=f"path: {path_str}\n---\n{content}", ok=True)

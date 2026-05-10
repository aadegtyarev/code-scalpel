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
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path

from code_scalpel.tools.files import list_files, read_file
from code_scalpel.tools.search import ripgrep
from code_scalpel.tools.shell import AsyncShellRunner, ShellRunner

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


async def execute(
    call: ToolCall,
    cwd: Path,
    *,
    max_lines: int = 400,
    runner: ShellRunner | None = None,
) -> ToolResult:
    """Dispatch a tool call by name. Returns a ToolResult — never raises."""
    if call.name == "read_file":
        return _tool_read_file(call, cwd, max_lines=max_lines)
    if call.name == "grep":
        return await _tool_grep(call, cwd, runner or AsyncShellRunner())
    if call.name == "run_tests":
        return await _tool_run_tests(call, cwd, runner or AsyncShellRunner())
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


async def _tool_grep(call: ToolCall, cwd: Path, runner: ShellRunner) -> ToolResult:
    """Body: pattern, optionally followed by a relative path on the next line."""
    body = call.body.strip()
    if not body:
        return ToolResult(call, output="error: missing pattern", ok=False)
    lines = body.splitlines()
    pattern = lines[0]
    where = cwd
    if len(lines) > 1:
        rel = lines[1].strip()
        if rel.startswith("/") or ".." in Path(rel).parts:
            return ToolResult(call, output=f"error: path must be inside project: {rel}", ok=False)
        where = cwd / rel
        if not where.exists():
            return ToolResult(call, output=f"error: path not found: {rel}", ok=False)
    if shutil.which("rg") is not None:
        try:
            matches = await ripgrep(pattern, where, runner, max_results=30, context_lines=0)
        except Exception as e:
            return ToolResult(call, output=f"error: {e}", ok=False)
    else:
        matches = _grep_python(pattern, where, cwd)
    if not matches:
        return ToolResult(call, output=f"no matches for {pattern!r}", ok=True)
    cwd_prefix = f"{cwd}/"
    pretty = matches.replace(cwd_prefix, "")
    return ToolResult(call, output=pretty, ok=True)


def _grep_python(pattern: str, where: Path, cwd: Path, *, max_results: int = 30) -> str:
    """Fallback grep when ripgrep is not installed. Slower but dependency-free."""
    flags = re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error:
        regex = re.compile(re.escape(pattern), flags)
    targets: list[Path] = (
        [where] if where.is_file() else [where / p for p in list_files(where, max_files=2000)]
    )
    out: list[str] = []
    for path in targets:
        try:
            with path.open(errors="replace") as f:
                for i, line in enumerate(f, start=1):
                    if regex.search(line):
                        out.append(f"{path}:{i}:{line.rstrip()}")
                        if len(out) >= max_results:
                            return "\n".join(out)
        except OSError:
            continue
    return "\n".join(out)


_MAX_TEST_OUTPUT = 4000


async def _tool_run_tests(call: ToolCall, cwd: Path, runner: ShellRunner) -> ToolResult:
    """Body: optional pytest args (e.g. 'tests/test_foo.py' or '-k pattern').
    Empty body = run full test suite."""
    args = shlex.split(call.body.strip()) if call.body.strip() else []
    cmd = ["pytest", "-x", "--tb=short", "--no-header", "-q", *args]
    try:
        result = await runner.run(cmd, cwd=str(cwd), timeout=120)
    except Exception as e:
        return ToolResult(call, output=f"error: {e}", ok=False)
    text = result.stdout
    if len(text) > _MAX_TEST_OUTPUT:
        text = (
            text[:_MAX_TEST_OUTPUT] + f"\n... ({len(text) - _MAX_TEST_OUTPUT} more bytes truncated)"
        )
    summary = f"exit code: {result.returncode}\n---\n{text}"
    return ToolResult(call, output=summary, ok=result.returncode == 0)

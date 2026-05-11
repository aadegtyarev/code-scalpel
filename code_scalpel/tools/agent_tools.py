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

import json
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_scalpel.tools.files import list_files, read_file
from code_scalpel.tools.search import ripgrep
from code_scalpel.tools.shell import AsyncShellRunner, ShellRunner

# OpenAI tools schema — sent with chat() so the model can call them natively.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a project file in full. Returns the file content with "
                "line numbers. You MUST call this in any of these cases:\n"
                "(1) Before producing a SEARCH/REPLACE block for that file — "
                "your SEARCH text has to match the file character-for-"
                "character including the body, and the MAP doesn't show "
                "bodies. Using a MAP signature as SEARCH text will fail.\n"
                "(2) The user asks you to SHOW, QUOTE, or DISPLAY a function/"
                "method body, or a file's content.\n"
                "(3) You're about to claim a fact about what a method does, "
                "what its arguments look like, or what fields a class has — "
                "anything beyond the top-level signature listed in the MAP.\n"
                "(4) You're about to describe an algorithm 'step by step', "
                "number the steps a function takes, or explain 'how it "
                "works' internally. Signatures + docstrings let you LOCATE "
                "the function; they do not let you correctly enumerate the "
                "branches, loops, or local variables inside it. Inventing "
                "steps that aren't in the source is a common bug — read the "
                "file first.\n"
                "The MAP contains signatures only — no function bodies, no "
                "field defaults, no decorators. Recognising a familiar "
                "pattern (dataclass, BaseModel) is NOT a substitute for "
                "this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Relative path from the project root, exactly as "
                            "it appears in the MAP. No leading 'path/' prefix."
                        ),
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "map_file",
            "description": (
                "Drill into ONE file's structural details: top-level "
                "classes, functions, methods with their signatures, "
                "first-sentence docstrings, and intra-project imports. "
                "This is the per-file table-of-contents — what was on "
                "the bigger MAP before we switched to navigation. "
                "Call this when you need to decide which file to read "
                "for the user's question: look at file's outline first, "
                "then read_file the body if needed. Cheaper than "
                "read_file (signatures only, no bodies) and gives the "
                "imports line so you can trace the dependency graph."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Relative path from the project root, exactly "
                            "as it appears in the OVERVIEW. No leading "
                            "'path/' prefix."
                        ),
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": (
                "Search the project (or a subdirectory) for a regex pattern. "
                "Returns up to 30 matching lines. Call this whenever the user "
                "asks WHERE / FIND / IS THERE something, or before answering "
                "a 'does X exist' question. Prefer grep over read_file when "
                "you don't yet know which file holds the symbol."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for.",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Optional relative path. Omit to search the whole project."
                        ),
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": (
                "Run the project's pytest suite. Returns exit code and truncated output."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "string",
                        "description": (
                            "Optional pytest args (e.g. 'tests/test_x.py' or '-k name'). "
                            "Empty to run everything."
                        ),
                    }
                },
            },
        },
    },
]

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
    if call.name == "map_file":
        return _tool_map_file(call, cwd)
    if call.name == "grep":
        return await _tool_grep(call, cwd, runner or AsyncShellRunner())
    if call.name == "run_tests":
        return await _tool_run_tests(call, cwd, runner or AsyncShellRunner())
    return ToolResult(
        call=call,
        output=f"error: unknown tool {call.name!r}",
        ok=False,
    )


def _decode_args(body: str) -> dict[str, Any]:
    """Tool args can come either as JSON (native function calling) or as raw
    text (legacy <TOOL> format). Try JSON first, fall back to legacy."""
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
    return {"_raw": body}


def _tool_read_file(call: ToolCall, cwd: Path, *, max_lines: int) -> ToolResult:
    args = _decode_args(call.body)
    path_str = str(args.get("path", args.get("_raw", ""))).strip()
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


def _tool_map_file(call: ToolCall, cwd: Path) -> ToolResult:
    """args: {path: str}. Returns the per-file outline block from
    build_file_map — signatures + docstrings + intra-project imports."""
    from code_scalpel.project_map import build_file_map

    args = _decode_args(call.body)
    path_str = str(args.get("path") or args.get("_raw", "")).strip()
    if not path_str:
        return ToolResult(call, output="error: missing file path", ok=False)
    if path_str.startswith("/") or ".." in Path(path_str).parts:
        return ToolResult(
            call, output=f"error: path must be inside the project: {path_str}", ok=False
        )
    try:
        block = build_file_map(cwd, path_str)
    except OSError as e:
        return ToolResult(call, output=f"error: {e}", ok=False)
    ok = not block.endswith(": file not found") and not block.endswith(": unreadable")
    return ToolResult(call, output=block, ok=ok)


async def _tool_grep(call: ToolCall, cwd: Path, runner: ShellRunner) -> ToolResult:
    """args: {pattern: str, path?: str}. Legacy text body also supported:
    first line is pattern, second is optional path."""
    args = _decode_args(call.body)
    if "_raw" in args:
        lines = args["_raw"].splitlines()
        pattern = lines[0].strip() if lines else ""
        rel = lines[1].strip() if len(lines) > 1 else ""
    else:
        pattern = str(args.get("pattern", "")).strip()
        rel = str(args.get("path", "")).strip()
    if not pattern:
        return ToolResult(call, output="error: missing pattern", ok=False)
    where = cwd
    if rel:
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
    """args: {args?: str}. Legacy: raw pytest args."""
    decoded = _decode_args(call.body)
    raw = str(decoded.get("args", decoded.get("_raw", ""))).strip()
    args = shlex.split(raw) if raw else []
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

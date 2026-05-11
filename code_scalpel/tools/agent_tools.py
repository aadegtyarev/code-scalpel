"""Tools the LLM can invoke during an agent turn.

The default protocol is OpenAI-compatible native function calling —
TOOL_SCHEMAS is sent with each chat() request and the model emits
structured `tool_calls` in the response. The agent dispatches each
call through `execute()`, feeds the result back as a tool-role
message, and loops until the model produces a turn with no tool
calls (then we look for SEARCH/REPLACE blocks).

The legacy `<TOOL: name>` / `</TOOL>` text format is still parsed as
a fallback for older / non-function-calling models — see
`parse_tool_calls` and `_TOOL_RE`. Don't write new code against it.

Current tools: read_file, map_file, goto_definition, find_references,
grep, retrieve, run_tests. Schemas with normative descriptions live in
TOOL_SCHEMAS below.
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
            "name": "list_files",
            "description": (
                "List project files with line counts: `path [N L]` per "
                "row. Use FIRST when the user's task mentions the "
                "project without a specific file name — you need to "
                "know what files exist before you can pick which one "
                "to read. Optional `path` narrows to a subdirectory. "
                "Cheaper than map_file (no symbols, no imports) — only "
                "use this for orientation. Once you spot the right "
                "file, call map_file or read_file on it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Optional relative subdirectory. Omit to list the whole project."
                        ),
                    },
                },
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
            "name": "goto_definition",
            "description": (
                "Find where a top-level name is defined: class, function, "
                "or method. Returns each definition site as "
                "`path:line  kind  qualified_name` — straight pointer "
                "with no body, no signature dump. Call this when the "
                "user asks WHERE a specific symbol is defined / lives. "
                "Cheaper and more precise than grep — grep returns "
                "every textual mention; this returns only the def. "
                "If nothing matches, fall back to grep for a broader "
                "lexical search."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Exact identifier to look up. No dots, no "
                            "parens. For 'where is Class.method', pass "
                            "just `method` and read the qualified_name "
                            "column to disambiguate which class owns it."
                        ),
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_references",
            "description": (
                "List every line in the project that mentions `name` as a "
                "whole word. Returns `path:line: code` rows, capped to "
                "50. This is the 'where is X USED?' tool — paired with "
                "goto_definition (the 'where is X DEFINED?' tool). "
                "Includes imports and comments because users routinely "
                "ask 'where does X get imported' or 'who has a TODO "
                "about X' — both legitimate references that AST-only "
                "search would miss."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Exact identifier; word-bounded match.",
                    }
                },
                "required": ["name"],
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
            "name": "retrieve",
            "description": (
                "Search the project for symbols (classes, functions, methods) "
                "whose name or docstring matches keywords from `query`. "
                "Returns top-10 ranked hits as "
                "`path:line  kind  qualified_name  · docstring`. Use when "
                "you know roughly WHAT you want but not the exact symbol "
                "name — fuzzier than `goto_definition`, more structured "
                "than `grep`. Optional `path` narrows the search to one "
                "file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Free-text keywords. Split on whitespace + "
                            "punctuation; tokens are matched case-"
                            "insensitively against symbol names and "
                            "docstrings."
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Optional relative path to scope the search "
                            "to one file. Omit to search the whole project."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": (
                "Run the project's test suite via the active SkillRegistry skill "
                "(pytest, docker, …). Returns exit code + truncated output."
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
    if call.name == "list_files":
        return _tool_list_files(call, cwd)
    if call.name == "map_file":
        return _tool_map_file(call, cwd)
    if call.name == "goto_definition":
        return _tool_goto_definition(call, cwd)
    if call.name == "find_references":
        return _tool_find_references(call, cwd)
    if call.name == "grep":
        return await _tool_grep(call, cwd, runner or AsyncShellRunner())
    if call.name == "retrieve":
        return _tool_retrieve(call, cwd)
    if call.name == "run_tests":
        return await _tool_run_tests(call, cwd, runner or AsyncShellRunner())
    return ToolResult(
        call=call,
        output=f"error: unknown tool {call.name!r}",
        ok=False,
    )


def _is_inside_project(target: Path, cwd: Path) -> bool:
    """True iff `target` (after symlink resolution) actually lives under
    `cwd`. The lexical "startswith / .." check is the first gate, but
    a symlink inside the project pointing outside (e.g. a tracked
    `secrets -> /etc/shadow`) walks past it — `is_file()` follows
    symlinks. Calling `resolve()` on both sides catches that without
    leaking error detail to the model.

    `is_relative_to` requires the target to exist for symlink
    resolution to behave; non-existent paths return False here and
    upstream callers handle the missing-file case separately.
    """
    try:
        return target.resolve().is_relative_to(cwd.resolve())
    except (OSError, ValueError):
        return False


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
    # Reject absolute / parent-escaping paths (lexical gate)
    if path_str.startswith("/") or ".." in Path(path_str).parts:
        return ToolResult(
            call, output=f"error: path must be inside the project: {path_str}", ok=False
        )
    path = cwd / path_str
    if not path.is_file():
        return ToolResult(call, output=f"error: file not found: {path_str}", ok=False)
    # Symlink gate — a tracked symlink could point at /etc/shadow even
    # though the lexical path is clean. Resolve and verify containment.
    if not _is_inside_project(path, cwd):
        return ToolResult(
            call, output=f"error: path must be inside the project: {path_str}", ok=False
        )
    try:
        content = read_file(path, max_lines=max_lines)
    except OSError as e:
        return ToolResult(call, output=f"error: {e}", ok=False)
    return ToolResult(call, output=f"path: {path_str}\n---\n{content}", ok=True)


def _tool_goto_definition(call: ToolCall, cwd: Path) -> ToolResult:
    """args: {name: str}. Returns one row per definition site —
    `path:line  kind  qualified_name`. Empty result is `ok=True` but
    with a clear "no definition found" message so the model knows to
    fall back to grep rather than re-asking with a typo."""
    from code_scalpel.project_map import find_definitions

    args = _decode_args(call.body)
    name = str(args.get("name") or args.get("_raw", "")).strip()
    if not name:
        return ToolResult(call, output="error: missing 'name'", ok=False)
    try:
        defs = find_definitions(cwd, name)
    except OSError as e:
        return ToolResult(call, output=f"error: {e}", ok=False)
    if not defs:
        return ToolResult(
            call,
            output=f"no definition found for {name!r}. Try `find_references` or `grep`.",
            ok=True,
        )
    lines = [f"{d.rel_path}:{d.line}  {d.kind}  {d.qualified_name}" for d in defs]
    return ToolResult(call, output="\n".join(lines), ok=True)


def _tool_find_references(call: ToolCall, cwd: Path) -> ToolResult:
    """args: {name: str}. Returns `path:line: code` rows, capped to 50."""
    from code_scalpel.project_map import find_references

    args = _decode_args(call.body)
    name = str(args.get("name") or args.get("_raw", "")).strip()
    if not name:
        return ToolResult(call, output="error: missing 'name'", ok=False)
    try:
        refs = find_references(cwd, name)
    except OSError as e:
        return ToolResult(call, output=f"error: {e}", ok=False)
    if not refs:
        return ToolResult(call, output=f"no references found for {name!r}.", ok=True)
    lines = [f"{r.rel_path}:{r.line}: {r.text}" for r in refs]
    return ToolResult(call, output="\n".join(lines), ok=True)


def _tool_retrieve(call: ToolCall, cwd: Path) -> ToolResult:
    """args: {query: str, path?: str}. Returns top-10 ranked symbol hits
    as `path:line  kind  qualified_name  · docstring`. Empty result is
    `ok=True` with a hint to fall back to grep — same shape as
    goto_definition so the agent treats it uniformly."""
    from code_scalpel.index.retrieve import search

    args = _decode_args(call.body)
    query = str(args.get("query") or args.get("_raw", "")).strip()
    if not query:
        return ToolResult(call, output="error: missing 'query'", ok=False)
    rel = str(args.get("path", "")).strip()
    if rel:
        if rel.startswith("/") or ".." in Path(rel).parts:
            return ToolResult(
                call, output=f"error: path must be inside the project: {rel}", ok=False
            )
        if not _is_inside_project(cwd / rel, cwd):
            return ToolResult(
                call, output=f"error: path must be inside the project: {rel}", ok=False
            )
    try:
        hits = search(cwd, query, path=rel or None)
    except OSError as e:
        return ToolResult(call, output=f"error: {e}", ok=False)
    if not hits:
        return ToolResult(
            call,
            output=(f"no symbol hits for {query!r}. Try grep for textual matches."),
            ok=True,
        )
    lines = [
        (
            f"{h.rel_path}:{h.lineno}  {h.kind}  {h.qualified_name}"
            + (f"  · {h.docstring}" if h.docstring else "")
        )
        for h in hits
    ]
    return ToolResult(call, output="\n".join(lines), ok=True)


def _tool_list_files(call: ToolCall, cwd: Path) -> ToolResult:
    """args: {path?: str}. Returns one row per file: `path [N L]`.
    Uses the lightweight overview builder from project_map — same
    output shape the user gets from /map but tool-callable."""
    from code_scalpel.project_map import build_map_overview

    args = _decode_args(call.body)
    rel = str(args.get("path") or args.get("_raw", "")).strip()
    where = cwd
    if rel:
        if rel.startswith("/") or ".." in Path(rel).parts:
            return ToolResult(call, output=f"error: path must be inside project: {rel}", ok=False)
        where = cwd / rel
        if not where.exists():
            return ToolResult(call, output=f"error: path not found: {rel}", ok=False)
        if not _is_inside_project(where, cwd):
            return ToolResult(call, output=f"error: path must be inside project: {rel}", ok=False)
    try:
        listing = build_map_overview(where, max_files=200)
    except OSError as e:
        return ToolResult(call, output=f"error: {e}", ok=False)
    if not listing:
        return ToolResult(call, output="(no files)", ok=True)
    return ToolResult(call, output=listing, ok=True)


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
    # Symlink gate — same reasoning as _tool_read_file.
    if not _is_inside_project(cwd / path_str, cwd):
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
        if not _is_inside_project(where, cwd):
            return ToolResult(call, output=f"error: path must be inside project: {rel}", ok=False)
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
    """args: {args?: str}. Legacy: raw pytest args.

    Dispatches through `default_skill(cwd)` so the active stack picks
    its own test runner (PythonSkill → pytest, DockerSkill → compose).
    If no skill detects the project shape, falls back to the historical
    hardcoded `pytest -x --tb=short --no-header -q …` so the tool still
    works on bare scratch directories (most tests, demos, fresh clones).
    """
    from code_scalpel.skills import default_skill

    decoded = _decode_args(call.body)
    raw = str(decoded.get("args", decoded.get("_raw", ""))).strip()

    skill = default_skill(cwd)
    if skill is not None:
        cmd = skill.test_cmd(raw)
        skill_label = skill.name
    else:
        args = shlex.split(raw) if raw else []
        cmd = ["pytest", "-x", "--tb=short", "--no-header", "-q", *args]
        skill_label = "pytest (fallback)"

    try:
        result = await runner.run(cmd, cwd=str(cwd), timeout=120)
    except Exception as e:
        return ToolResult(call, output=f"using skill: {skill_label}\nerror: {e}", ok=False)
    text = result.stdout
    if len(text) > _MAX_TEST_OUTPUT:
        text = (
            text[:_MAX_TEST_OUTPUT] + f"\n... ({len(text) - _MAX_TEST_OUTPUT} more bytes truncated)"
        )
    summary = f"using skill: {skill_label}\nexit code: {result.returncode}\n---\n{text}"
    return ToolResult(call, output=summary, ok=result.returncode == 0)

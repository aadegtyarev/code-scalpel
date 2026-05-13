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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from code_scalpel.tools.files import list_files, read_file
from code_scalpel.tools.search import ripgrep
from code_scalpel.tools.shell import AsyncShellRunner, ShellResult, ShellRunner

# Awaitable callback the dispatch invokes when a shell command needs
# the user's blessing before running (skeptic trust level). Returns
# True to approve, False to refuse.
ConfirmShellExec = Callable[[str], Awaitable[bool]]

# OpenAI tools schema — sent with chat() so the model can call them natively.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the body of a file with 1-based line numbers. "
                "Three modes — pick by which args you pass:\n"
                "• whole file: just `path` (caps at 400 lines, then "
                "`… N more lines` footer).\n"
                "• window: `path` + `start_line` and/or `end_line` "
                "(1-based, inclusive). Use after a project_map hit or "
                "a failing-test line number — drops you straight onto "
                "the region.\n"
                "• find: `path` + `find=<substring>` returns every "
                "match plus `context` lines around it (default 20), "
                "merged into non-overlapping windows. Use when you "
                "want to read around a name without knowing its line."
                "\nHeavy — use only when you need the actual code. For "
                "'what's in this file', use `project_map(path=...)`."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from the project root.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": (
                            "Optional. 1-based start of the window. "
                            "If omitted but end_line is set, defaults "
                            "to 1."
                        ),
                    },
                    "end_line": {
                        "type": "integer",
                        "description": (
                            "Optional. 1-based end of the window "
                            "(inclusive). If omitted, extends to "
                            "start_line + 400 or end of file."
                        ),
                    },
                    "find": {
                        "type": "string",
                        "description": (
                            "Optional substring search. Returns every "
                            "hit plus `context` lines around it. "
                            "Mutually exclusive with the window args."
                        ),
                    },
                    "context": {
                        "type": "integer",
                        "description": (
                            "Optional lines-of-context for `find` mode "
                            "(default 20). Ignored without `find`."
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
            "name": "write_file",
            "description": (
                "Write to a file. Three modes — pick by which args you pass:\n"
                "• overwrite/create: `path` + `content`. Replaces the whole "
                "file (creates if missing). Use for new files and small "
                "rewrites.\n"
                "• replace lines: `path` + `content` + `start_line` + "
                "`end_line` (1-based, inclusive). Replaces only those lines. "
                "Use for surgical edits in large files.\n"
                "• insert: `path` + `content` + `insert_after_line` (1-based; "
                "use 0 to prepend). Inserts the content after that line.\n"
                "Always pass the literal content — newlines preserved. Use "
                "this instead of shell_exec for any file write."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from the project root.",
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "File content as a single string. In overwrite "
                            "mode: the whole file. In replace/insert mode: "
                            "just the chunk to put in."
                        ),
                    },
                    "start_line": {
                        "type": "integer",
                        "description": (
                            "Replace mode: 1-based first line to replace "
                            "(inclusive). Requires `end_line`."
                        ),
                    },
                    "end_line": {
                        "type": "integer",
                        "description": (
                            "Replace mode: 1-based last line to replace "
                            "(inclusive). Requires `start_line`."
                        ),
                    },
                    "insert_after_line": {
                        "type": "integer",
                        "description": (
                            "Insert mode: 1-based line number to insert AFTER. "
                            "Use 0 to prepend at the top. Mutually exclusive "
                            "with start_line/end_line."
                        ),
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "project_map",
            "description": (
                "See what's in the project — files, classes, "
                "functions, methods. No bodies. Without `path` — a "
                "list of files with line counts. With `path` set to "
                "a file — that file's classes/functions/methods with "
                "their signatures and imports (no implementation). "
                "Prefer this over `read_file` for 'what's there' "
                "questions; reach for read_file only when you need "
                "the actual code body."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Optional file or directory path.",
                    },
                },
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


# Skills loading — lazy injection of stack-specific knowledge.
# Catalog of available skills is always in the system prompt; the model
# calls these to add (or remove) detailed test/lint/format guidance to
# its context for the current turn. Dispatched in `Agent._execute_native`
# (needs agent state — not stateless like the file/grep tools above).
LOAD_SKILL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "Load a skill to get stack-specific guidance — exact test/lint/"
            "format commands and project rules. Call early on a coding task "
            "once you know the stack (e.g. saw pyproject.toml → load_skill("
            "'python')). See the 'Available skills' catalog in the system "
            "prompt for valid names."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name from the catalog, e.g. 'python', 'go', 'js'.",
                }
            },
            "required": ["name"],
        },
    },
}

UNLOAD_SKILL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "unload_skill",
        "description": (
            "Unload a previously loaded skill when it's no longer relevant "
            "for the current task. Frees context for unrelated work."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name to unload.",
                }
            },
            "required": ["name"],
        },
    },
}


# Optional — gated on `agent.trust`. Agent includes this in the tool list
# only when trust is `optimist` or `yolo` (skeptic awaits the confirmation
# UI). See `code_scalpel/policy.py` for the level semantics.
SHELL_EXEC_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "shell_exec",
        "description": (
            "Run an arbitrary shell command in the project root. Useful for "
            "mass edits (sed/awk/find) or git plumbing that SEARCH/REPLACE "
            "would be a waste for. Hard-blocked from rm -rf /, dd of=/dev/*, "
            "mkfs, sudo, pipe-to-shell, and fork bombs even in optimist mode. "
            "Returns combined stdout+stderr and the exit code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Full shell command to run, as it would be typed in "
                        "a terminal. Quote strings as needed; do NOT prepend "
                        "`bash -c`."
                    ),
                }
            },
            "required": ["command"],
        },
    },
}

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
    trust: str = "skeptic",
    shell_exec_timeout: int = 30,
    confirm_shell_exec: ConfirmShellExec | None = None,
    sandbox: str = "off",
) -> ToolResult:
    """Dispatch a tool call by name. Returns a ToolResult — never raises.

    `trust`, `shell_exec_timeout`, `confirm_shell_exec` are only
    consulted for the `shell_exec` path; pass them at the call site
    to keep dispatch a single boundary.

    `confirm_shell_exec(command)` is awaited in skeptic mode for
    non-hard-blocked commands. Return True to approve, False to
    refuse. When the callback is `None` and confirm is required,
    the command is refused with a clear message — keeps headless
    callers (probe, bench) from accidentally running shell on a
    user's machine."""
    if call.name == "read_file":
        return _tool_read_file(call, cwd, max_lines=max_lines)
    if call.name == "write_file":
        return _tool_write_file(call, cwd)
    # `project_map` is the unified entry — empty path → tree, path → file
    # outline. Legacy `list_files` and `map_file` names stay routed for
    # one cycle of backwards compatibility (some early bench fixtures /
    # external scripts may still call them by old names).
    if call.name == "project_map":
        return _tool_project_map(call, cwd)
    if call.name == "list_files":
        return _tool_project_map(call, cwd)  # legacy alias → tree mode
    if call.name == "map_file":
        return _tool_project_map(call, cwd)  # legacy alias → drilldown mode
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
    if call.name == "shell_exec":
        return await _tool_shell_exec(
            call,
            cwd,
            runner or AsyncShellRunner(),
            trust=trust,
            timeout=shell_exec_timeout,
            confirm=confirm_shell_exec,
            sandbox=sandbox,
        )
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
    # Optional slicing args — keep raw read_file as the fallback for
    # whole-file reads while letting the model land on a specific region
    # of a long file without burning context on the rest.
    start_line = _coerce_int(args.get("start_line"))
    end_line = _coerce_int(args.get("end_line"))
    find_str = args.get("find")
    find_arg = str(find_str).strip() if isinstance(find_str, str) and find_str.strip() else None
    context_lines = _coerce_int(args.get("context"))
    try:
        content = read_file(
            path,
            max_lines=max_lines,
            start_line=start_line,
            end_line=end_line,
            find=find_arg,
            context=context_lines if context_lines is not None else 20,
        )
    except OSError as e:
        return ToolResult(call, output=f"error: {e}", ok=False)
    return ToolResult(call, output=f"path: {path_str}\n---\n{content}", ok=True)


def _coerce_int(value: Any) -> int | None:
    """Some clients pass numeric args as strings — accept both."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


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


def _tool_write_file(call: ToolCall, cwd: Path) -> ToolResult:
    """Three modes: overwrite (default), replace lines, insert at line.

    Dispatch by which args are present — same shape as `read_file`. Path
    validation gates mirror `_tool_read_file`; the resolved parent must
    live under `cwd` (symlink-escape gate)."""
    args = _decode_args(call.body)
    path_str = str(args.get("path", "")).strip()
    content = args.get("content", "")
    if not path_str:
        return ToolResult(call, output="error: missing file path", ok=False)
    if not isinstance(content, str):
        return ToolResult(call, output="error: content must be a string", ok=False)
    # v0.9 loose end C: 14b sometimes calls write_file twice with the
    # same path and content="", clobbering whatever the previous turn
    # produced. Refuse the empty case explicitly — if you really want
    # an empty file, the model can use `content="\n"` or shell_exec
    # touch. The error nudges the model to pick the right tool.
    if content == "":
        return ToolResult(
            call,
            output=(
                'error: empty content. write_file rejects content="" to avoid '
                'overwriting existing files with nothing. Use content="\\n" for '
                "a deliberately blank file, or shell_exec `touch <path>`."
            ),
            ok=False,
        )
    if path_str.startswith("/") or ".." in Path(path_str).parts:
        return ToolResult(
            call, output=f"error: path must be inside the project: {path_str}", ok=False
        )
    target = cwd / path_str
    try:
        parent = target.parent.resolve()
        if not parent.is_relative_to(cwd.resolve()):
            return ToolResult(
                call, output=f"error: path must be inside the project: {path_str}", ok=False
            )
    except (OSError, ValueError):
        return ToolResult(call, output=f"error: invalid path: {path_str}", ok=False)

    # Coerce numeric args; tolerate string ints (some models stringify).
    def _coerce_int(name: str) -> int | None:
        raw = args.get(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    start_line = _coerce_int("start_line")
    end_line = _coerce_int("end_line")
    insert_after = _coerce_int("insert_after_line")

    # Mode resolution — explicit checks so we can return clear errors.
    mode_replace = start_line is not None or end_line is not None
    mode_insert = insert_after is not None
    if mode_replace and mode_insert:
        return ToolResult(
            call,
            output="error: cannot use insert_after_line together with start_line/end_line",
            ok=False,
        )
    if mode_replace and (start_line is None or end_line is None):
        return ToolResult(
            call, output="error: replace mode needs both start_line and end_line", ok=False
        )

    final_content: str
    summary: str
    if mode_replace:
        if not target.is_file():
            return ToolResult(
                call, output=f"error: file not found: {path_str} (replace mode)", ok=False
            )
        # mypy/lint: start_line/end_line are non-None inside this branch.
        assert start_line is not None and end_line is not None
        if start_line < 1 or end_line < start_line:
            return ToolResult(
                call,
                output=f"error: invalid line range start={start_line} end={end_line}",
                ok=False,
            )
        original = target.read_text()
        lines = original.splitlines(keepends=True)
        if start_line > len(lines):
            return ToolResult(
                call,
                output=f"error: start_line {start_line} > file length {len(lines)}",
                ok=False,
            )
        clamped_end = min(end_line, len(lines))
        new_chunk = content if content.endswith("\n") else content + "\n"
        final_content = "".join(lines[: start_line - 1]) + new_chunk + "".join(lines[clamped_end:])
        summary = f"replaced lines {start_line}-{clamped_end} in {path_str}"
    elif mode_insert:
        assert insert_after is not None
        if insert_after < 0:
            return ToolResult(
                call,
                output=f"error: insert_after_line must be >= 0 (got {insert_after})",
                ok=False,
            )
        if target.is_file():
            original = target.read_text()
            lines = original.splitlines(keepends=True)
        else:
            # Insert into a new file is just "create with this content";
            # insert_after must be 0 to make sense in that case.
            if insert_after != 0:
                return ToolResult(
                    call,
                    output=f"error: file not found: {path_str} (insert_after={insert_after})",
                    ok=False,
                )
            lines = []
        chunk = content if content.endswith("\n") else content + "\n"
        anchor = min(insert_after, len(lines))
        final_content = "".join(lines[:anchor]) + chunk + "".join(lines[anchor:])
        summary = f"inserted at line {anchor + 1} of {path_str}"
    else:
        final_content = content
        summary = f"wrote {path_str}"

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(final_content)
    except OSError as e:
        return ToolResult(call, output=f"error: {e}", ok=False)
    line_count = final_content.count("\n") + (
        0 if final_content.endswith("\n") or not final_content else 1
    )
    return ToolResult(
        call,
        output=f"{summary} ({line_count} lines, {len(final_content)} chars total)",
        ok=True,
    )


def _tool_project_map(call: ToolCall, cwd: Path) -> ToolResult:
    """args: {path?: str}. Two modes:
      - no path → tree: `path [N L]` per row (whole project)
      - path → file outline (symbols + imports), OR subdir tree if
        the path is a directory.

    A single tool with mode-by-argument was preferred over two
    separate names — weak models split attention across "two tools
    that sound similar" and the unified entry pushes them toward
    the right call shape.
    """
    from code_scalpel.project_map import build_file_map, build_map_overview

    args = _decode_args(call.body)
    rel = str(args.get("path") or args.get("_raw", "")).strip()

    if not rel:
        # Tree mode: whole project listing.
        try:
            listing = build_map_overview(cwd, max_files=200)
        except OSError as e:
            return ToolResult(call, output=f"error: {e}", ok=False)
        return ToolResult(call, output=listing or "(no files)", ok=True)

    # Path provided — share path-safety with read_file et al.
    if rel.startswith("/") or ".." in Path(rel).parts:
        return ToolResult(call, output=f"error: path must be inside the project: {rel}", ok=False)
    target = cwd / rel
    if not target.exists():
        return ToolResult(call, output=f"error: path not found: {rel}", ok=False)
    if not _is_inside_project(target, cwd):
        return ToolResult(call, output=f"error: path must be inside the project: {rel}", ok=False)

    if target.is_dir():
        # Subdir mode: tree under the directory.
        try:
            listing = build_map_overview(target, max_files=200)
        except OSError as e:
            return ToolResult(call, output=f"error: {e}", ok=False)
        return ToolResult(call, output=listing or "(no files)", ok=True)

    # File mode: outline.
    try:
        block = build_file_map(cwd, rel)
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
    from code_scalpel.skills import default_runnable_skill

    decoded = _decode_args(call.body)
    raw = str(decoded.get("args", decoded.get("_raw", ""))).strip()

    # `default_runnable_skill` skips component-only skills (Postgres,
    # SQLite — no own test runner). On a Python+Postgres repo this keeps
    # `pytest` as the test command rather than letting Postgres steal
    # the slot with an empty cmd.
    skill = default_runnable_skill(cwd)
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


_MAX_SHELL_OUTPUT = 4000

# Match `mkdir <path>` or `mkdir -p <path>` with NO further chaining
# (`&&`, `;`, `|`, redirects). The model's pattern is exactly this —
# one mkdir then a separate write_file — and we want to keep the gate
# narrow so legitimate compound mkdir invocations still pass.
_MKDIR_NOOP_RE = re.compile(r"^mkdir(?:\s+-p)?\s+(?P<path>[^\s|&;<>]+)\s*$")


async def _run_argv_unchecked(argv: list[str], cwd: Path, timeout: int) -> ShellResult:
    """Run an argv directly via asyncio, bypassing AsyncShellRunner's
    whitelist. Used for the `bwrap` wrapping path: bwrap itself isn't on
    the default whitelist, and growing it would let the model invoke
    bwrap directly (with whatever bind args it wants). Keeping the bypass
    local to this function preserves the whitelist's value for the
    rest of the tool surface."""
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(cwd),
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise
    return ShellResult(
        stdout=stdout.decode(errors="replace"),
        returncode=proc.returncode if proc.returncode is not None else 0,
    )


async def _tool_shell_exec(
    call: ToolCall,
    cwd: Path,
    runner: ShellRunner,
    *,
    trust: str,
    timeout: int,
    confirm: ConfirmShellExec | None = None,
    sandbox: str = "auto",
) -> ToolResult:
    """args: `{command: str}` — arbitrary shell command (pipes, redirects,
    quoting all work, no `bash -c` wrapping needed).

    Policy via `code_scalpel.policy.decide(command, trust)`:
      • hard-blocked (rm -rf /abs, sudo, mkfs, dd of=/dev/*, pipe-to-
        shell, fork bomb) — refused regardless of trust except yolo.
      • optimist / non-blocked — runs.
      • skeptic / non-blocked — needs interactive confirmation. Caller
        provides `confirm(command) -> bool`; without one the command
        is refused (probe / bench: no UI).
      • yolo — runs unconditionally.

    Output is truncated to `_MAX_SHELL_OUTPUT` chars with an explicit
    marker so the model sees the cut. Combined stdout+stderr — same
    shape as `run_tests`.
    """
    from code_scalpel.policy import decide

    decoded = _decode_args(call.body)
    command = str(decoded.get("command", decoded.get("_raw", ""))).strip()
    if not command:
        return ToolResult(call, output="error: empty command", ok=False)

    # v0.9 loose end B: 14b habitually prefixes a write_file with
    # `mkdir <dir>` even though write_file creates parents itself.
    # In sandbox the mkdir fails (exit 1, no -p) — and even when it
    # succeeds it wastes a turn and triggers a useless confirmation
    # in skeptic mode. Recognize the simple single-dir case and
    # treat it as a no-op with an honest warning. Compound commands
    # (`mkdir x && do_thing`, pipes, redirects) fall through to the
    # real shell so we don't strip user intent.
    mkdir_match = _MKDIR_NOOP_RE.match(command)
    if mkdir_match:
        target = mkdir_match.group("path")
        return ToolResult(
            call,
            output=(
                f"no-op: skipped `mkdir {target}` — write_file creates parent "
                "directories itself. If you actually need an empty directory "
                f"on disk, use `mkdir -p {target}` (it stays no-op when the "
                "dir exists), or just call write_file with a path inside it."
            ),
            ok=True,
        )

    # `trust` is typed as `str` at the public boundary; the policy module
    # is typed strictly. cast at the boundary; unknown values get
    # coerced to "skeptic" inside `decide` for safety.
    decision = decide(command, trust)  # type: ignore[arg-type]
    if not decision.allowed:
        return ToolResult(call, output=f"refused: {decision.reason}", ok=False)
    if decision.requires_confirm:
        if confirm is None:
            return ToolResult(
                call,
                output=(
                    "refused: shell_exec at trust=skeptic needs a "
                    "confirmation handler — none was registered. Build "
                    "the agent through ScalpelApp (which wires the UI) "
                    "or set trust to 'optimist' / 'yolo'."
                ),
                ok=False,
            )
        approved = await confirm(command)
        if not approved:
            return ToolResult(call, output="refused: user rejected the command", ok=False)

    # Sandbox dispatch — wrap with bwrap when available + enabled. We use
    # `runner.run` (argv form) for the wrapped path because bwrap takes its
    # OWN argv and then invokes `/bin/sh -c <command>` internally. Plain
    # `run_shell` would double-wrap with another `sh -c`.
    from code_scalpel.tools.sandbox import bwrap_available, wrap_command_with_bwrap

    use_sandbox = False
    if sandbox == "on":
        if not bwrap_available():
            return ToolResult(
                call,
                output=(
                    "refused: sandbox=on requires bwrap (bubblewrap), but it is "
                    "not on PATH. Install the `bubblewrap` package or switch to "
                    "sandbox='auto' / 'off'."
                ),
                ok=False,
            )
        use_sandbox = True
    elif sandbox == "auto":
        use_sandbox = bwrap_available()

    try:
        if use_sandbox:
            argv = wrap_command_with_bwrap(command, cwd)
            # The bwrap argv goes through the bypass-whitelist `run_shell`-
            # adjacent path: AsyncShellRunner.run() enforces a whitelist
            # by argv[0], but `bwrap` itself is not on it. Use the dedicated
            # `_run_argv_bypassing_whitelist` if present; else fall back via
            # asyncio directly so we don't have to grow the whitelist.
            result = await _run_argv_unchecked(argv, cwd, timeout)
        else:
            result = await runner.run_shell(command, cwd=str(cwd), timeout=timeout)
    except TimeoutError:
        return ToolResult(call, output=f"timeout after {timeout}s", ok=False)
    except Exception as e:
        return ToolResult(call, output=f"error: {e}", ok=False)

    text = result.stdout
    if len(text) > _MAX_SHELL_OUTPUT:
        text = (
            text[:_MAX_SHELL_OUTPUT]
            + f"\n... ({len(text) - _MAX_SHELL_OUTPUT} more bytes truncated)"
        )
    sandbox_tag = " (sandboxed)" if use_sandbox else ""
    summary = f"exit code: {result.returncode}{sandbox_tag}\n---\n{text}"
    return ToolResult(call, output=summary, ok=result.returncode == 0)


# Re-export so the module-level `from code_scalpel.policy import TrustLevel`
# in tests doesn't have to dig into the policy module separately.
__all__ = (
    "LOAD_SKILL_SCHEMA",
    "SHELL_EXEC_SCHEMA",
    "TOOL_SCHEMAS",
    "ToolCall",
    "UNLOAD_SKILL_SCHEMA",
    "ToolResult",
    "execute",
    "format_result",
    "parse_tool_calls",
)

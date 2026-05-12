from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.geometry import Offset, Region, Spacing
from textual.widget import Widget
from textual.widgets import Rule
from textual_autocomplete import AutoComplete, DropdownItem

from code_scalpel.agent import (
    PatchAttempt,
    RetryNotice,
    StepAgent,
    TextDelta,
    ToolExecuted,
    UsageReport,
)
from code_scalpel.config import AppConfig, autodetect_context_tokens, resolve_model_name
from code_scalpel.diagrams import extract_mermaid_blocks
from code_scalpel.jobs import JobRegistry
from code_scalpel.llm.adapter import ChatResponse
from code_scalpel.memory import MemoryStore
from code_scalpel.patch.edit_block import Edit, apply_edits, edits_to_diff, extract_edits
from code_scalpel.runtime import Runtime
from code_scalpel.session import Session
from code_scalpel.state import AgentState
from code_scalpel.tools.agent_tools import ToolCall, ToolResult
from code_scalpel.tools.shell import AsyncShellRunner
from code_scalpel.tui.widgets.cards.tool_call import PatchDecision, ToolCallCard
from code_scalpel.tui.widgets.footer import StatusFooter
from code_scalpel.tui.widgets.input import ModeInput, UserMessage
from code_scalpel.tui.widgets.jobs_bar import JobsBar
from code_scalpel.tui.widgets.jobs_modal import JobsModal
from code_scalpel.tui.widgets.mermaid_card import MermaidCard
from code_scalpel.tui.widgets.output import OutputLog
from code_scalpel.tui.widgets.tool_result_modal import ToolResultModal
from code_scalpel.tui.widgets.tool_use import ToolUseCard


class _UpwardAutoComplete(AutoComplete):
    """AutoComplete that opens above the target — input sits at the screen bottom."""

    def _align_to_target(self) -> None:
        x, y = self.target.cursor_screen_offset
        width, height = self.option_list.outer_size
        new_y = max(0, y - height)
        rx, ry, _w, _h = Region(x - 1, new_y, width, height).constrain(
            "inside",
            "none",
            Spacing.all(0),
            self.screen.scrollable_content_region,
        )
        self.absolute_offset = Offset(rx, ry)


_SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/new", "start a new session — clear chat and reset state"),
    ("/compact", "summarize history to free up context (not yet)"),
    ("/map", "project tree; /map foo.py → file outline; /map subdir → subdir tree"),
    ("/tasks", "show plan; /tasks rm T### drops one; /tasks clear wipes the file"),
    ("/stats", "show this session's token/cost/timing stats"),
    ("/context", "breakdown of context budget by category"),
    ("/skills", "list available tools and slash commands"),
    ("/remember", "save a project note (e.g. /remember always run linter)"),
    ("/recall", "browse stored notes; with text — search them"),
    ("/loop", "toggle code-mode iterative patch loop (apply → test → retry)"),
    ("/run", "walk TASKS.md unattended — one task at a time, stop on N failures"),
    (
        "/learn",
        "generate a recipe markdown (.code-scalpel/recipes/<name>.md); /learn skill <name> for a skill",
    ),
    ("/help", "list commands"),
    ("/mode ask", "switch to ask mode"),
    ("/mode plan", "switch to plan mode"),
    ("/mode code", "switch to code mode"),
    ("/mode review", "switch to review mode"),
]


def _format_turn_summary(
    *,
    tool_calls: int,
    rate: float,
    completion_tokens: int,
    duration: float,
) -> str:
    """One-line summary printed inline after each turn.

    Ctx usage moved to the footer (continuous state, every keystroke
    moves it — not just turns). Turn summary keeps the per-turn cost
    picture: how many tools were invoked, how many tokens came back,
    at what rate, how long it took. Tool count is omitted when zero
    so a zero-tool reply doesn't carry a misleading "0 tools" badge."""
    parts: list[str] = []
    if tool_calls > 0:
        noun = "tool" if tool_calls == 1 else "tools"
        parts.append(f"🔧 {tool_calls} {noun}")
    if completion_tokens:
        parts.append(f"↓ {completion_tokens} tokens")
    if rate:
        parts.append(f"{rate:.0f} tok/s")
    if duration > 0:
        parts.append(f"{duration:.1f}s")
    return "⤷ " + " · ".join(parts)


class ScalpelApp(App[None]):
    CSS_PATH = ["styles.tcss"]

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+t", "cycle_mode", "Mode", show=False),
        Binding("ctrl+o", "show_last_tool_result", "Open last tool result", show=False),
        Binding("ctrl+j", "show_jobs", "Show background jobs", show=False),
        Binding("ctrl+y", "copy_focused", "Copy focused card output", show=False),
        Binding("ctrl+up", "focus_prev_card", "Previous tool card", show=False),
        Binding("ctrl+down", "focus_next_card", "Next tool card", show=False),
        Binding("escape", "cancel_step", "Cancel", show=False),
    ]

    _AGENT_MODES: tuple[str, ...] = ("ask", "plan", "code", "review")

    def __init__(self, config: AppConfig, cwd: Path = Path(".")) -> None:
        super().__init__()
        self.config = config
        self.cwd = cwd
        self.state = AgentState.load(cwd)
        self._mode_index = 0
        self._pending_edits: list[Edit] | None = None
        self._last_stream_rate: float = 0.0
        # Real token usage stashed by `_run_first_attempt_streamed` so the
        # /loop path can hand it to `_record_loop_usage` without threading
        # it through every branch of the patch-loop control flow.
        self._last_stream_usage: UsageReport | None = None
        self._runner = AsyncShellRunner()
        # Headless runtime — built lazily in `_init_agent` so config /
        # adapter errors land on the OutputLog rather than during compose.
        # `self.session`, `self._agent`, and `self._memory` are surfaced
        # as bridge fields for legacy call sites; they all point into the
        # runtime once it's built.
        self.runtime: Runtime | None = None
        self.session = Session()  # replaced by runtime.session in _init_agent
        self._agent: StepAgent | None = None
        # Latest tool round-trip from the agent — Ctrl+O opens it in a modal.
        self._last_tool_result: ToolResult | None = None
        # Project-scoped persistent memory. Materialised by the Runtime;
        # legacy code reads through this bridge field.
        self._memory: MemoryStore | None = None
        # In-session registry of background jobs (map build, LLM step,
        # /compact, pytest retry, …). The JobsBar widget subscribes; any
        # worker that wants to be visible wraps itself in
        # `self.jobs.track(kind, description)`.
        self.jobs = JobRegistry()

    # ── compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield OutputLog()
        yield Rule(line_style="solid", classes="input-rule")
        yield ModeInput(mode=self._AGENT_MODES[0])
        yield Rule(line_style="solid", classes="input-rule")
        # JobsBar sits between the input rule and the footer; collapses to
        # height 0 (display:none) when idle so the user gets the row back.
        yield JobsBar(self.jobs)
        yield StatusFooter()
        yield _UpwardAutoComplete(
            target="#textarea",
            candidates=[DropdownItem(cmd) for cmd, _ in _SLASH_COMMANDS],
            prevent_default_enter=False,
        )

    def on_mount(self) -> None:
        self.query_one(ModeInput).focus_input()
        self._update_footer()
        self._init_agent()
        self._show_resume_notice()
        self.run_worker(self._detect_context(), exclusive=False)

    async def on_unmount(self) -> None:
        """Capture a session summary for stdout on exit — printed by main().
        Uses the full `stats_report` (multi-line: model / mode / requests /
        elapsed / tokens / rate / context / cost) because the one-liner
        loses everything that the user cares about when reviewing
        what a session cost. We still pass through if anything throws —
        a broken summary must never block exit."""
        from contextlib import suppress

        try:
            mode = self._AGENT_MODES[self._mode_index]
            model: str | None = None
            with suppress(KeyError, ValueError):
                model = self.config.current_profile.model
            report = self.session.stats_report(
                ctx_limit=self.state.context_limit or None,
                model=model,
                mode=mode,
            )
        except Exception:
            return
        self._exit_summary = "Session summary:\n" + report

    _exit_summary: str | None = None

    def _show_resume_notice(self) -> None:
        """If STATE.json reports an interrupted session, surface that inline so
        the user knows they may need to roll back uncommitted changes."""
        if self.state.dirty_patch:
            output = self.query_one(OutputLog)
            output.print_status(
                "● Previous session ended with an unfinished patch. "
                "Working tree may have stale edits — review with `git diff` "
                "or `git restore .` if you want to discard them."
            )
            # Clear the flag so we don't nag every launch
            self.state.dirty_patch = False
            self.state.save(self.cwd)

    def _init_agent(self) -> None:
        try:
            self.runtime = Runtime(cwd=self.cwd, config=self.config)
            # Bridge the runtime's quartet to legacy fields so the rest of
            # the TUI keeps using `self._agent`, `self.session`,
            # `self._memory` unchanged. New code should reach through
            # `self.runtime` directly.
            self._agent = self.runtime.agent
            self.session = self.runtime.session
            self._memory = self.runtime.memory
            # Footer shows configured name until resolve_model_name finishes.
            self.query_one(StatusFooter).model = self.config.current_profile.model
        except (KeyError, ValueError) as e:
            self.query_one(OutputLog).print_error(f"Config error: {e}")

    async def _detect_context(self) -> None:
        """One-shot startup discovery: model name and context window. Both
        come from the same /v1/models endpoint, so we do them together —
        cuts the round-trip count in half and keeps the footer's two
        right-side fields in sync."""
        try:
            profile = self.config.current_profile
            model_name = await resolve_model_name(profile)
            tokens = await autodetect_context_tokens(profile)
            footer = self.query_one(StatusFooter)
            footer.model = model_name
            # Adapter was built with profile.model (likely "auto"); replace
            # so the next request carries the real id and logs cleanly.
            if self._agent is not None and model_name != profile.model:
                self._agent._llm.set_model(model_name)
            if tokens:
                self.state.context_limit = tokens
                self._update_footer()
        except Exception:
            pass

    # ── user message ──────────────────────────────────────────────────────────

    def on_user_message(self, message: UserMessage) -> None:
        mode = self._AGENT_MODES[self._mode_index]
        output = self.query_one(OutputLog)
        output.print_user(f"{mode} › {message.text}")
        if message.text.startswith("/"):
            self._handle_slash(message.text.strip())
            return

        if self.runtime is None:
            output.print_error("No LLM configured — check config.")
            return

        self.query_one(StatusFooter).status = "◌ thinking…"
        # Raw text flows through to _run_step / _run_code_with_retry; the
        # Runtime adds the language directive at the agent boundary. One
        # prepare_turn, one channel — see code_scalpel/runtime.py.
        text = message.text
        # In code mode with the iterative loop opted in, swap the regular
        # streaming step for the auto apply→test→retry path. The streaming
        # path stays untouched for ask/plan/review so opt-out is a clean
        # one-flag flip — no behaviour leaks across modes.
        use_loop = mode == "code" and self.config.agent.iterative_patch_loop
        coro = self._run_code_with_retry(text) if use_loop else self._run_step(text, mode=mode)
        # Defer worker until after refresh so the user message lands first
        self.call_after_refresh(
            lambda: setattr(
                self,
                "_step_worker",
                self.run_worker(coro, exclusive=True, group="step"),
            )
        )

    async def _do_map(self, arg: str = "") -> None:
        """Same view the model gets from `project_map()`:
          /map           — tree of project files
          /map foo.py    — outline of foo.py (classes, functions,
                            methods, imports)
          /map subdir    — tree of files under subdir
        Inline "● Building project map…" lands before the work
        starts; the build itself runs off the event loop so a
        large repo doesn't freeze the UI."""
        output = self.query_one(OutputLog)
        output.print_status("● Building project map…", markup=True)
        await asyncio.sleep(0)
        from code_scalpel.project_map import build_file_map, build_map_overview

        arg = arg.strip()
        loop = asyncio.get_running_loop()
        with self.jobs.track("map", "Building project map"):
            if not arg:
                try:
                    text = await loop.run_in_executor(
                        None, lambda: build_map_overview(self.cwd, max_files=200)
                    )
                except OSError as e:
                    output.print_error(f"project_map failed: {e}")
                    return
                body_arg = ""
            else:
                target = self.cwd / arg
                if not target.exists():
                    output.print_error(f"path not found: {arg}")
                    return
                if target.is_dir():
                    try:
                        text = await loop.run_in_executor(
                            None, lambda: build_map_overview(target, max_files=200)
                        )
                    except OSError as e:
                        output.print_error(f"project_map failed: {e}")
                        return
                else:
                    try:
                        text = await loop.run_in_executor(None, build_file_map, self.cwd, arg)
                    except OSError as e:
                        output.print_error(f"project_map failed: {e}")
                        return
                body_arg = f'{{"path": "{arg}"}}'
        text = text or "(no files)"
        call = ToolCall(name="project_map", body=body_arg)
        result = ToolResult(call=call, output=text, ok=True)
        output.add_tool_use(call, result)
        self._last_tool_result = result

    def _do_tasks(self, arg: str = "") -> None:
        """Surface the current plan (.code-scalpel/TASKS.md) inline.

        Subcommands:
          /tasks           — show the plan
          /tasks clear     — delete the file
          /tasks rm T001   — drop one task by id (keeps the rest)
        """
        output = self.query_one(OutputLog)
        tasks_path = self.cwd / ".code-scalpel" / "TASKS.md"
        arg = arg.strip()

        if arg == "clear":
            if tasks_path.is_file():
                try:
                    tasks_path.unlink()
                except OSError as e:
                    output.print_error(f"TASKS.md delete failed: {e}")
                    return
                output.print_status("● TASKS.md cleared.")
            else:
                output.print_status("No plan to clear.")
            return

        if arg.startswith("rm "):
            target = arg.removeprefix("rm").strip()
            if not target:
                output.print_error("Usage: /tasks rm T###")
                return
            if not tasks_path.is_file():
                output.print_status("No plan yet.")
                return
            try:
                from code_scalpel.plan import parse_tasks_md, serialize_tasks
            except Exception as e:
                output.print_error(f"plan parser unavailable: {e}")
                return
            original = tasks_path.read_text()
            tasks = list(parse_tasks_md(original))
            kept = tuple(t for t in tasks if t.id != target)
            if len(kept) == len(tasks):
                output.print_error(f"task {target!r} not found.")
                return
            new_text = serialize_tasks(kept, original)
            tmp = tasks_path.with_suffix(".md.tmp")
            try:
                tmp.write_text(new_text)
                tmp.replace(tasks_path)
            except OSError as e:
                output.print_error(f"TASKS.md write failed: {e}")
                return
            output.print_status(f"● Dropped {target}.")
            return

        # Default: show the plan.
        if not tasks_path.is_file():
            output.print_status("No plan yet. Switch to plan mode and ask for a breakdown.")
            return
        try:
            text = tasks_path.read_text()
        except OSError as e:
            output.print_error(f"TASKS.md read failed: {e}")
            return
        call = ToolCall(name="tasks_md", body="")
        result = ToolResult(call=call, output=text, ok=True)
        output.add_tool_use(call, result)
        self._last_tool_result = result

    def _do_context(self) -> None:
        """Render a context-budget breakdown by category. Reads the
        same building blocks the agent would send on the next turn
        (system prompt, tools schema, overview, skills, history) so
        the user sees ground-truth, not a guess from session counters.

        Skills feed into the Skills segment even though they're not
        currently injected into the model prompt — the cost shown is
        what we WOULD pay if/when we wire them in, an honest preview
        of /skills cost rather than a permanent zero."""
        import json

        from code_scalpel.agent import _PLAN_MODE_ADDENDUM, _SYSTEM_PROMPT
        from code_scalpel.context_report import build
        from code_scalpel.skills import active_skills
        from code_scalpel.tools.agent_tools import TOOL_SCHEMAS

        output = self.query_one(OutputLog)
        model = self.config.current_profile.model
        mode = self._AGENT_MODES[self._mode_index]
        system = _SYSTEM_PROMPT + (_PLAN_MODE_ADDENDUM if mode == "plan" else "")
        tools_text = json.dumps(TOOL_SCHEMAS)
        try:
            skills_text = "\n".join(f"{s.name}: {s.description}" for s in active_skills(self.cwd))
        except Exception:
            skills_text = ""
        # Project listing is no longer auto-injected — it lives behind
        # the `list_files` tool now. Its cost lands in Conversation
        # if/when the model calls it, not in a permanent segment.
        # Stringify history as the model sees it — role + content per row
        # joined. `/context` runs its own len/4 estimate over this string;
        # session.context_used_tokens uses the API-reported prompt size
        # directly, so the two numbers can differ by a small overhead.
        history = ""
        if self._agent is not None:
            history = "\n".join(
                f"{m.get('role', '')}: {m.get('content', '')}" for m in self._agent.history
            )
        report = build(
            model=model,
            ctx_limit=self.state.context_limit,
            system_prompt=system,
            tools_schema_text=tools_text,
            recall_text="",
            history_text=history,
            skills_text=skills_text,
        )
        call = ToolCall(name="context_report", body="")
        result = ToolResult(call=call, output=report.render(), ok=True)
        output.add_tool_use(call, result, full=True)
        self._last_tool_result = result

    def _do_skills(self) -> None:
        """Surface what the agent / TUI can currently do — built-in tools
        (function-calling), slash commands, and detected user skills.

        The skills section is the live SkillRegistry view: every skill
        whose `detect()` fires for `self.cwd` is listed with its name,
        description and rough token cost. Built-ins (Python, Docker)
        appear automatically; user-registered skills appear once they
        call `register_skill(...)`."""
        import json

        from code_scalpel.skills import active_skills
        from code_scalpel.tools.agent_tools import TOOL_SCHEMAS

        lines: list[str] = []
        lines.append("Tools — exposed to the model via function calling")
        for spec in TOOL_SCHEMAS:
            fn = spec.get("function", {})
            name = fn.get("name", "?")
            desc_full = str(fn.get("description", "")).strip()
            # First sentence only — descriptions in TOOL_SCHEMAS are
            # multi-paragraph (normative for the model); /skills wants a
            # one-line summary the user can scan.
            first = desc_full.split(".", 1)[0].strip().replace("\n", " ")
            if len(first) > 110:
                first = first[:107] + "…"
            tokens = max(0, len(json.dumps(spec)) // 4)
            lines.append(f"  {name:<18} {tokens:>4}t  {first}")

        lines.append("")
        lines.append("Skills (detected) — pluggable per-stack contracts (test / lint / format)")
        skills = active_skills(self.cwd)
        if not skills:
            lines.append("  (none detected for this project)")
        else:
            for skill in skills:
                desc = skill.description.replace("\n", " ").strip()
                if len(desc) > 110:
                    desc = desc[:107] + "…"
                lines.append(f"  {skill.name:<18} {skill.token_cost():>4}t  {desc}")

        lines.append("")
        lines.append("Slash commands — TUI-side surface")
        for cmd, hint in _SLASH_COMMANDS:
            lines.append(f"  {cmd:<18}     {hint}")

        lines.append("")
        lines.append(
            "Skills detected from your project — pluggable. `register_skill(...)` to add your own."
        )
        text = "\n".join(lines)

        output = self.query_one(OutputLog)
        call = ToolCall(name="skills", body="")
        result = ToolResult(call=call, output=text, ok=True)
        output.add_tool_use(call, result, full=True)
        self._last_tool_result = result

    def _do_stats(self) -> None:
        """Surface accumulated session stats as a collapsed ToolUseCard —
        same shape as /map and /tasks. The footer already shows live ctx,
        but the footer can't fit elapsed time, total cost, model id,
        average tok/s, or the compact baseline — /stats is the place for
        the full picture when the user asks for it."""
        output = self.query_one(OutputLog)
        model = self.config.current_profile.model
        mode = self._AGENT_MODES[self._mode_index]
        text = self.session.stats_report(
            ctx_limit=self.state.context_limit,
            model=model,
            mode=mode,
        )
        call = ToolCall(name="session_stats", body="")
        result = ToolResult(call=call, output=text, ok=True)
        # Small fixed body — render inline, no "N more lines" footer.
        output.add_tool_use(call, result, full=True)
        self._last_tool_result = result

    def _get_memory(self) -> MemoryStore:
        """Lazy MemoryStore — built on first /remember or /recall (or
        whenever the agent is wired). Tests that never trigger memory
        usage get no .code-scalpel/memory.db on disk."""
        if self._memory is None:
            self._memory = MemoryStore(root=self.cwd)
            # Hand the same instance to the live agent if it already exists
            # — otherwise the agent's recall would miss anything saved this
            # session until the next /new.
            if self._agent is not None:
                self._agent.attach_memory(self._memory)
        return self._memory

    def _do_remember(self, text: str) -> None:
        """/remember <fact> — persist one note. The agent recalls top-3
        matches automatically on every turn, so this is the user's way
        of teaching project conventions or past decisions without
        re-typing them each session."""
        output = self.query_one(OutputLog)
        text = text.strip()
        if not text:
            output.print_error("Usage: /remember <fact to save>")
            return
        try:
            mem = self._get_memory()
            mem.add(text, source="slash:remember")
        except Exception as e:
            output.print_error(f"Memory error: {e}")
            return
        output.print_status(f"● Remembered: {text}")

    def _do_recall(self, query: str) -> None:
        """/recall <query> — preview what the agent would pull on a turn
        with this task. No-arg form lists ALL stored notes (newest first)
        as a sanity check."""
        output = self.query_one(OutputLog)
        try:
            mem = self._get_memory()
        except Exception as e:
            output.print_error(f"Memory error: {e}")
            return
        query = query.strip()
        if query:
            hits = mem.search(query, k=10)
            label = f"recall(query={query!r}, k=10)"
        else:
            hits = list(reversed(mem.all()))  # newest first
            label = f"recall(all, count={len(hits)})"
        if not hits:
            output.print_status("● No memory hits.")
            return
        body = "\n".join(f"- {h.text}" for h in hits)
        call = ToolCall(name="recall", body=label)
        result = ToolResult(call=call, output=body, ok=True)
        # Small payload; render full inline like /stats.
        output.add_tool_use(call, result, full=True)
        self._last_tool_result = result

    def _do_learn(self, arg: str) -> None:
        """`/learn <name>` — recipe (default).
        `/learn skill <name>` — skill.
        `/learn <name> --url <url>` — fetch URL, convert HTML→markdown,
        feed to model as authoritative source.

        Off-loop because the model call is slow; the user sees an inline
        "Generating…" status and can keep working in the input."""
        from code_scalpel.learn import Kind, learn

        output = self.query_one(OutputLog)
        if self.runtime is None:
            output.print_error("No LLM configured — check config.")
            return

        # Strip `--url <url>` anywhere in the arg before parsing the name.
        # Keeps positional handling identical to the no-URL form below.
        url: str | None = None
        url_match = re.search(r"--url\s+(\S+)", arg)
        if url_match is not None:
            url = url_match.group(1)
            arg = (arg[: url_match.start()] + arg[url_match.end() :]).strip()

        parts = arg.split(maxsplit=1)
        kind: Kind = "recipe"
        if parts and parts[0] == "skill":
            kind = "skill"
            name = parts[1].strip() if len(parts) > 1 else ""
        elif parts and parts[0] == "recipe":
            # explicit form `/learn recipe <name>` for symmetry
            name = parts[1].strip() if len(parts) > 1 else ""
        else:
            name = arg.strip()
        if not name:
            output.print_error(
                "Usage: /learn <name> [--url URL]  or  /learn skill <name> [--url URL]"
            )
            return

        runtime = self.runtime  # capture for closure — narrows the type for mypy

        async def _go() -> None:
            footer = self.query_one(StatusFooter)
            label = f"{kind} from URL" if url else kind
            footer.status = f"◌ learning {label}: {name}…"
            with self.jobs.track("learn", f"learn {label}: {name}"):
                try:
                    saved = await learn(runtime, name, kind=kind, url=url)
                except Exception as e:
                    output.print_error(f"/learn failed: {e}")
                    footer.status = "● error"
                    return
                rel = saved.relative_to(self.cwd) if saved.is_relative_to(self.cwd) else saved
                output.print_status(f"● Saved {kind}: {rel}")
                footer.status = "● idle"

        self.call_after_refresh(lambda: self.run_worker(_go(), exclusive=False, group="learn"))

    async def _do_compact(self) -> None:
        output = self.query_one(OutputLog)
        footer = self.query_one(StatusFooter)
        assert self._agent is not None
        with self.jobs.track("compact", "Summarising history"):
            footer.status = "◌ compacting…"
            try:
                summary = await self._agent.compact()
            except Exception as e:
                output.print_error(f"Compact failed: {e}")
                footer.status = "● error"
                return
            if summary is None:
                output.print_status("Nothing to compact.")
            else:
                output.print_status(f"● Compacted. Summary:\n{summary}")
                # Anchor the footer budget to "post-compact" so the bar drops.
                self.session.mark_compacted()
                self._update_ctx()
            footer.status = "● idle"

    def action_cancel_step(self) -> None:
        # Esc on a focused tool card returns the user to the input rather
        # than cancelling — they almost certainly meant "I'm done browsing
        # cards, let me type again", not "kill the live step".
        if self._focused_card() is not None:
            self.query_one(ModeInput).focus_input()
            return
        w = getattr(self, "_step_worker", None)
        if w is not None and not w.is_finished:
            w.cancel()

    def action_show_last_tool_result(self) -> None:
        """Ctrl+O: open the most recent tool result in a modal with full
        content and syntax highlighting. Plan §v0.3 hook."""
        if self._last_tool_result is None:
            self.query_one(OutputLog).print_status("● No tool result yet in this session.")
            return
        self.push_screen(ToolResultModal(self._last_tool_result))

    def action_show_jobs(self) -> None:
        """Ctrl+J: open the full jobs view. JobsBar (inline above the
        footer) only shows kinds; this modal carries description and
        elapsed age per job — the picture you need when supervised
        autonomous mode is running and several things stack up."""
        self.push_screen(JobsModal(self.jobs))

    def action_copy_focused(self) -> None:
        """Ctrl+Y: copy the focused ToolUseCard's raw output into the
        system clipboard. Terminal mouse-selection inside Textual is
        blocked because the framework captures mouse events for its
        own interactions — Ctrl+Y is the keyboard-only escape hatch.
        Yank-style binding (emacs/readline tradition); Ctrl+C would
        collide with the input's standard "abort" semantics."""
        from code_scalpel.clipboard import copy_to_system_clipboard

        card = self._focused_card()
        if card is None:
            self.notify(
                "Focus a tool card first (Ctrl+↑/↓) before pressing Ctrl+Y.",
                title="Copy",
                severity="warning",
                timeout=2,
            )
            return
        text = card._result.output or ""
        if not text:
            self.notify("Card output is empty.", title="Copy", timeout=2)
            return
        method = copy_to_system_clipboard(text)
        if method is None:
            try:
                self.copy_to_clipboard(text)
                method = "OSC52"
            except Exception:
                self.notify(
                    "Couldn't copy — install xclip/wl-clipboard or use terminal selection.",
                    title="Copy",
                    severity="warning",
                    timeout=3,
                )
                return
        self.notify(
            f"Copied {len(text)} chars via {method}.",
            title="Copy",
            timeout=2,
        )

    def action_focus_prev_card(self) -> None:
        """Ctrl+↑ from input: jump to the most recent tool card. From an
        already-focused card: move toward older cards. Clamps at oldest
        instead of wrapping — wrap-around is disorienting when you can't
        see the whole chat at once."""
        self._step_card(-1)

    def action_focus_next_card(self) -> None:
        """Ctrl+↓: opposite direction. Past the newest card → back to
        input, mirroring how HistoryInput's ↓-past-newest restores draft."""
        self._step_card(+1)

    def _list_tool_cards(self) -> list[ToolUseCard]:
        return list(self.query_one(OutputLog).query(ToolUseCard))

    def _focused_card(self) -> ToolUseCard | None:
        """Return the ToolUseCard containing the currently-focused widget,
        or None if focus is elsewhere (input, footer, modal)."""
        focused = self.focused
        if focused is None:
            return None
        node: Any = focused
        while node is not None:
            if isinstance(node, ToolUseCard):
                return node
            node = getattr(node, "parent", None)
        return None

    def _step_card(self, direction: int) -> None:
        cards = self._list_tool_cards()
        if not cards:
            return
        current = self._focused_card()
        if current is None:
            # Coming from input. ↑ enters at the newest card; ↓ does
            # nothing — no "next" exists below the input.
            if direction < 0:
                cards[-1].focus_card()
            return
        idx = cards.index(current)
        new_idx = idx + direction
        if new_idx < 0:
            return  # already at oldest — clamp
        if new_idx >= len(cards):
            # Stepped past the newest card → drop focus back into the input.
            self.query_one(ModeInput).focus_input()
            return
        cards[new_idx].focus_card()

    def on_key(self, event: events.Key) -> None:
        """textual-autocomplete sometimes swallows Escape even when its
        dropdown is hidden. Catch it at the App level as a fallback."""
        if event.key == "escape":
            self.action_cancel_step()

    def _handle_slash(self, cmd: str) -> None:
        output = self.query_one(OutputLog)
        if cmd == "/new":
            for child in list(output.children):
                if child.id != "_spacer":
                    child.remove()
            self.session = Session()
            AgentState.reset(self.cwd)
            self.state = AgentState.load(self.cwd)
            if self._agent is not None:
                self._agent.clear_history()
            self._update_ctx()
            return
        if cmd == "/compact":
            if self._agent is None:
                output.print_error("No LLM configured.")
                return
            if not self._agent.history:
                output.print_status("Nothing to compact yet.")
                return
            self.run_worker(self._do_compact(), exclusive=True, group="step")
            return
        if cmd == "/help":
            lines = "Commands:\n" + "\n".join(f"  {c}  — {d}" for c, d in _SLASH_COMMANDS)
            output.print_status(lines)
            return
        if cmd == "/map" or cmd.startswith("/map "):
            # Off-loop build so a large repo doesn't freeze the UI;
            # subcommand parses to /map [path]. Empty path → tree,
            # file path → outline, subdir → tree under it.
            arg = cmd.removeprefix("/map").strip()
            self.run_worker(self._do_map(arg), exclusive=False, group="map")
            return
        if cmd == "/tasks" or cmd.startswith("/tasks "):
            # /tasks            — show plan
            # /tasks clear      — delete TASKS.md
            # /tasks rm T###    — drop one task
            arg = cmd.removeprefix("/tasks").strip()
            self._do_tasks(arg)
            return
        if cmd == "/stats":
            # Pure in-memory render — no I/O, no need for a worker.
            self._do_stats()
            return
        if cmd == "/context":
            # Synchronous: build_map_overview is ~50ms on this repo.
            # Worker-bounce + thread-switch latency dwarfed the work.
            self._do_context()
            return
        if cmd == "/skills":
            # Pure in-memory render — static catalog.
            self._do_skills()
            return
        if cmd == "/remember" or cmd.startswith("/remember "):
            self._do_remember(cmd.removeprefix("/remember"))
            return
        if cmd == "/recall" or cmd.startswith("/recall "):
            self._do_recall(cmd.removeprefix("/recall"))
            return
        if cmd == "/run":
            if self._agent is None:
                output.print_error("No LLM configured.")
                return
            tasks_path = self.cwd / ".code-scalpel" / "TASKS.md"
            if not tasks_path.is_file():
                output.print_status(
                    "● No plan yet. Switch to plan mode and ask for a breakdown first."
                )
                return
            # Same worker plumbing as a regular turn so Esc cancels via
            # `_step_worker` and JobsBar tracks the run in real time.
            self.call_after_refresh(
                lambda: setattr(
                    self,
                    "_step_worker",
                    self.run_worker(self._run_plan(), exclusive=True, group="step"),
                )
            )
            return
        if cmd == "/loop":
            # Flip the iterative patch loop on/off without editing config —
            # this is the user's opt-in for code-mode auto apply→test→retry.
            self.config.agent.iterative_patch_loop = not self.config.agent.iterative_patch_loop
            state = "on" if self.config.agent.iterative_patch_loop else "off"
            output.print_status(f"● Iterative patch loop: {state}")
            return
        if cmd == "/learn" or cmd.startswith("/learn "):
            # /learn <name>          — recipe (default)
            # /learn skill <name>    — skill
            self._do_learn(cmd.removeprefix("/learn").strip())
            return
        if cmd.startswith("/mode "):
            mode = cmd.removeprefix("/mode ").strip()
            if mode in self._AGENT_MODES:
                self._mode_index = self._AGENT_MODES.index(mode)
                self.query_one(ModeInput).set_mode(mode)
                self._update_footer()
            return
        output.print_status(f"Unknown command: {cmd}")

    async def _run_step(self, task: str, *, mode: str = "ask") -> None:
        import time

        output = self.query_one(OutputLog)
        footer = self.query_one(StatusFooter)
        assert self._agent is not None

        progress = output.start_turn_progress()
        placeholder = output.start_streaming()
        # Job covers the whole turn (stream + any tool round-trips +
        # post-processing). Mode is the more useful label here than
        # the generic "step" since the user sees ask/plan/code/review
        # in the input prompt.
        job_id = self.jobs.start(mode, f"{mode}: {task[:60]}")
        try:
            await self._wait_mounted(progress)
            await self._wait_mounted(placeholder)

            full = ""
            chunks = 0
            tool_calls = 0
            usage: UsageReport | None = None
            start = time.monotonic()
            last_tick = start
            assert self.runtime is not None
            async for item in self.runtime.stream(task, mode=mode):
                if isinstance(item, TextDelta):
                    full += item.text
                    chunks += 1
                    placeholder.update(full)
                    output.scroll_end(animate=False)
                    now = time.monotonic()
                    if now - last_tick > 0.25:
                        elapsed = now - start
                        # Live tick — we don't have the final usage payload
                        # yet, so the meter still leans on the char-count
                        # heuristic. The end-of-turn summary uses the real
                        # numbers from UsageReport.
                        approx_tokens = len(full) // 4
                        rate = chunks / elapsed if elapsed > 0 else 0.0
                        progress.update_progress(
                            tokens=approx_tokens,
                            tool_calls=tool_calls,
                            elapsed_s=elapsed,
                            rate_tok_s=rate,
                        )
                        last_tick = now
                elif isinstance(item, ToolExecuted):
                    tool_calls += 1
                    self._last_tool_result = item.result
                    placeholder.update(full)
                    await output.finalize_streaming(placeholder, full)
                    output.add_tool_use(item.call, item.result)
                    # Reflect the new tool count immediately — don't wait for
                    # the next text tick, which might not come if the model
                    # ends right after the tool call.
                    progress.update_progress(tool_calls=tool_calls)
                    full = ""
                    placeholder = output.start_streaming()
                    await self._wait_mounted(placeholder)
                elif isinstance(item, UsageReport):
                    usage = item
                elif isinstance(item, RetryNotice):
                    # HOOK fired. The first attempt's text was discarded
                    # from history; we also reset the visible buffer so
                    # the upcoming retry stream replaces it cleanly,
                    # instead of stacking under a now-stale answer.
                    await output.finalize_streaming(placeholder, "")
                    output.print_status(
                        f"↻ Re-reading {item.path} before patching",
                        markup=False,
                    )
                    full = ""
                    placeholder = output.start_streaming()
                    await self._wait_mounted(placeholder)
            # Final render: swap the streaming Static for a Markdown widget so
            # code fences and lists render properly.
            md = await output.finalize_streaming(placeholder, full)

            total_elapsed = time.monotonic() - start
            self._last_stream_rate = chunks / total_elapsed if total_elapsed > 0 else 0.0

            # The live progress line has served its purpose — the permanent
            # turn-summary line below carries the same data with the final
            # numbers. Two widgets at once would just be noise.
            await self._remove_progress(progress)

            # Real usage comes from the provider's final stream chunk
            # (`include_usage`). Fall back to the char-count heuristic only if
            # the provider didn't emit one — older LM Studio builds, etc. The
            # heuristic was lying about completion=0 whenever a turn ended on
            # a tool-call round with no follow-up text.
            if usage is not None:
                prompt_tokens = usage.prompt_tokens
                completion_tokens = usage.completion_tokens
            else:
                prompt_tokens = len(task) // 4 + 1000
                completion_tokens = len(full) // 4
            self.session.record(
                ChatResponse(
                    content=full,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost=None,
                )
            )
            self._update_ctx()

            # Inline turn summary — replaces the old crowded footer. Mounted
            # for every completed turn, before any review/apply card.
            summary = _format_turn_summary(
                tool_calls=tool_calls,
                rate=self._last_stream_rate,
                completion_tokens=completion_tokens,
                duration=total_elapsed,
            )
            output.print_turn_summary(summary)

            # Mermaid blocks render BEFORE the apply-card so the user sees
            # the diagram first and the patch dialog after — diagrams are
            # context, the dialog is action.
            for mermaid_src in extract_mermaid_blocks(full):
                output.run_worker(
                    output._append(MermaidCard(mermaid_src)),
                    exclusive=False,
                )

            edits = extract_edits(full)
            if edits:
                await md.remove()
                card = ToolCallCard("Apply", "")
                await self.mount(card, before=self.query_one(ModeInput))
                card.set_reviewing(edits_to_diff(edits, self.cwd))
                self._pending_edits = edits
                footer.status = "● reviewing"
            elif mode == "plan" and "## T" in full:
                # Plan mode delivered a structured plan. The natural-language
                # reply stays as Markdown; we add an inline PlanCard right
                # after, expanded by default, so the user can pick a task by
                # eye instead of re-reading the markdown.
                from code_scalpel.tui.widgets.plan_card import PlanCard

                plan_card = PlanCard.from_tasks_md(full)
                output.run_worker(output._append(plan_card), exclusive=False)
                footer.status = "● idle"
            else:
                footer.status = "● idle"
        except asyncio.CancelledError:
            await self._remove_progress(progress)
            output.print_status("● Cancelled.")
            footer.status = "● idle"
            raise
        except Exception as e:
            await self._remove_progress(progress)
            output.print_error(f"Error: {e}")
            footer.status = "● error"
        finally:
            # Cover every exit (success / cancel / error) — a stuck job
            # would otherwise stay in the JobsBar forever.
            self.jobs.finish(job_id)

    async def _run_code_with_retry(self, task: str) -> None:
        """Code mode + iterative_patch_loop: stream attempt 1 so the user
        sees tokens in real time (weak local 14B спокойно молчит 30-90 с),
        then — if attempt 1 didn't land — bounce through `code_with_retry`
        for the non-streamed retry sequence.

        Each rendered attempt becomes a `patch_attempt_{idx}` ToolUseCard
        whose body is the synthesised diff + test output. The card's ok dot
        tracks `attempt.tests_passed`, mirroring how every other tool card
        signals success/failure at a glance."""
        import time

        output = self.query_one(OutputLog)
        footer = self.query_one(StatusFooter)
        assert self._agent is not None

        max_attempts = self.config.agent.max_debug_attempts + 1
        start = time.monotonic()
        with self.jobs.track("code-retry", f"code: {task[:60]}"):
            footer.status = "◌ patch loop…"
            output.print_status(f"● Running patch loop (max attempts: {max_attempts})")
            try:
                first = await self._run_first_attempt_streamed(task)
            except asyncio.CancelledError:
                output.print_status("● Cancelled.")
                footer.status = "● idle"
                raise
            except Exception as e:
                output.print_error(f"Error: {e}")
                footer.status = "● error"
                return

            # No SEARCH/REPLACE blocks in the streamed reply — model
            # answered in plain text (question / "no change needed").
            # Loop has nothing to retry; mirror the regular ask path.
            if first is None:
                duration = time.monotonic() - start
                self._record_loop_usage(task, "", duration, 0)
                footer.status = "● idle"
                return

            attempt1, reply1 = first

            # Happy path: streamed attempt landed AND tests are green.
            # No need to invoke the retry pipeline at all.
            if attempt1.apply_ok and attempt1.tests_passed:
                call = ToolCall(name="patch_attempt_1", body="")
                body = self._render_attempt(attempt1)
                tool_result = ToolResult(call=call, output=body, ok=True)
                output.add_tool_use(call, tool_result)
                self._last_tool_result = tool_result
                duration = time.monotonic() - start
                self._record_loop_usage(task, reply1, duration, 1)
                output.print_status("● Patch loop succeeded after 1 attempt(s).")
                footer.status = "● idle"
                return

            # Attempt 1 didn't land. Hand off to `code_with_retry` for the
            # remaining attempts. It re-runs the model once more from
            # scratch (no way to pass attempt-1 history cheaply without
            # touching agent.py) and then iterates; we surface the full
            # set of attempts it tries, so the visible history is honest.
            try:
                assert self.runtime is not None
                result = await self.runtime.code_with_retry(task)
            except asyncio.CancelledError:
                output.print_status("● Cancelled.")
                footer.status = "● idle"
                raise
            except Exception as e:
                output.print_error(f"Error: {e}")
                footer.status = "● error"
                return

            attempts = result.attempts
            if not attempts:
                # Model degraded into plain-text on the non-streamed retry.
                # Surface its reply and bail — same as the no-edits branch.
                if result.reply:
                    output.print_assistant(result.reply)
                duration = time.monotonic() - start
                self._record_loop_usage(task, result.reply, duration, 0)
                footer.status = "● idle"
                return

            for idx, attempt in enumerate(attempts, start=1):
                call = ToolCall(name=f"patch_attempt_{idx}", body="")
                body = self._render_attempt(attempt)
                tool_result = ToolResult(call=call, output=body, ok=attempt.tests_passed)
                output.add_tool_use(call, tool_result)
                self._last_tool_result = tool_result

            duration = time.monotonic() - start
            self._record_loop_usage(task, result.reply, duration, len(attempts))

            final = attempts[-1]
            if final.tests_passed:
                output.print_status(f"● Patch loop succeeded after {len(attempts)} attempt(s).")
                footer.status = "● idle"
            else:
                # Gave up — fall back to the manual review flow so the user
                # keeps their escape hatch. They see every attempt above plus
                # a [a]/[r]/[g] card on the LAST diff.
                output.print_status(
                    f"✗ Gave up after {len(attempts)} attempt(s) — review diff manually."
                )
                last_edits = final.edits
                if last_edits:
                    card = ToolCallCard("Apply", "")
                    await self.mount(card, before=self.query_one(ModeInput))
                    card.set_reviewing(edits_to_diff(last_edits, self.cwd))
                    self._pending_edits = list(last_edits)
                    footer.status = "● reviewing"
                else:
                    footer.status = "● idle"

    async def _run_first_attempt_streamed(self, task: str) -> tuple[PatchAttempt, str] | None:
        """Stream the first /loop attempt so the user sees tokens instead
        of staring at a frozen screen for 30-90s. Returns:

        - None — model answered in plain text (no SEARCH/REPLACE blocks);
          treat as "no patch wanted", caller surfaces the reply.
        - (attempt, full_reply) — edits were extracted and we tried to
          apply + test them. The PatchAttempt mirrors what `code_with_retry`
          would produce for one iteration, so the caller can render it
          identically.

        The OutputLog placeholder is removed once we know the shape of the
        reply — we don't want the live token stream to linger AND a card
        to appear below it.
        """
        import time

        from code_scalpel.patch.edit_block import apply_edits

        output = self.query_one(OutputLog)
        assert self.runtime is not None

        progress = output.start_turn_progress()
        placeholder = output.start_streaming()
        await self._wait_mounted(progress)
        await self._wait_mounted(placeholder)

        full = ""
        chunks = 0
        tool_calls = 0
        start = time.monotonic()
        last_tick = start
        async for item in self.runtime.stream(task, mode="code"):
            if isinstance(item, TextDelta):
                full += item.text
                chunks += 1
                placeholder.update(full)
                output.scroll_end(animate=False)
                now = time.monotonic()
                if now - last_tick > 0.25:
                    elapsed = now - start
                    progress.update_progress(
                        tokens=len(full) // 4,
                        tool_calls=tool_calls,
                        elapsed_s=elapsed,
                        rate_tok_s=chunks / elapsed if elapsed > 0 else 0.0,
                    )
                    last_tick = now
            elif isinstance(item, ToolExecuted):
                tool_calls += 1
                self._last_tool_result = item.result
                placeholder.update(full)
                await output.finalize_streaming(placeholder, full)
                output.add_tool_use(item.call, item.result)
                progress.update_progress(tool_calls=tool_calls)
                full = ""
                placeholder = output.start_streaming()
                await self._wait_mounted(placeholder)
            elif isinstance(item, UsageReport):
                # The /loop path reads back the real usage through
                # `_last_stream_usage`; stashing it on the app avoids
                # threading an extra return value through every loop branch.
                self._last_stream_usage = item
            elif isinstance(item, RetryNotice):
                # HOOK fired mid-loop. Drop the unread first attempt from
                # the visible placeholder and surface the retry so the
                # user understands the second stream isn't a duplicate.
                await output.finalize_streaming(placeholder, "")
                output.print_status(
                    f"↻ Re-reading {item.path} before patching",
                    markup=False,
                )
                full = ""
                placeholder = output.start_streaming()
                await self._wait_mounted(placeholder)

        # The live stream is done; we'll render the result as cards from
        # here on. Clean up the placeholder/progress so they don't sit
        # under the upcoming attempt card.
        await self._remove_progress(progress)
        try:
            if placeholder.is_mounted:
                await placeholder.remove()
        except Exception:
            pass

        edits = extract_edits(full)
        if not edits:
            # Plain text — surface as assistant reply and bail. No
            # patch to apply, nothing to retry.
            if full:
                output.print_assistant(full)
            return None

        ok, err = apply_edits(edits, self.cwd)
        if not ok:
            return (
                PatchAttempt(
                    edits=tuple(edits),
                    apply_ok=False,
                    apply_error=err,
                    test_output="",
                    tests_passed=False,
                ),
                full,
            )
        # Apply succeeded — run tests through the agent (mirrors how
        # `code_with_retry` measures pass/fail).
        assert self._agent is not None
        test_output, tests_passed = await self._agent._run_tests()
        return (
            PatchAttempt(
                edits=tuple(edits),
                apply_ok=True,
                apply_error="",
                test_output=test_output,
                tests_passed=tests_passed,
            ),
            full,
        )

    async def _run_plan(self) -> None:
        """Walk `.code-scalpel/TASKS.md` unattended through code_with_retry.

        Per-task inline rendering: a "● Running T00N: <title>" status
        line before each iteration, then the same `patch_attempt_*`
        cards the manual code-mode flow already produces, followed by
        a one-line verdict per task. A final summary line closes the
        run (tasks done, failed, stop reason).
        """
        import time

        output = self.query_one(OutputLog)
        footer = self.query_one(StatusFooter)
        assert self._agent is not None

        start = time.monotonic()
        with self.jobs.track("run-plan", "Executing TASKS.md"):
            footer.status = "◌ run-plan…"

            # Hooks run from the worker thread context (same loop). They
            # mount widgets through OutputLog's `run_worker` plumbing, so
            # they're non-blocking.
            def _start(task: Any) -> None:
                output.print_status(f"● Running {task.id}: {task.title}")

            def _end(outcome: Any) -> None:
                step_result = outcome.step_result
                attempts = step_result.attempts if step_result is not None else ()
                for idx, attempt in enumerate(attempts, start=1):
                    call = ToolCall(name=f"{outcome.task.id}_attempt_{idx}", body="")
                    body = self._render_attempt(attempt)
                    tr = ToolResult(call=call, output=body, ok=attempt.tests_passed)
                    output.add_tool_use(call, tr)
                    self._last_tool_result = tr
                verdict = {
                    "done": "✓ done",
                    "failed": "✗ failed — rolled back",
                    "skipped": "↷ skipped (model emitted no patch)",
                }.get(outcome.status, outcome.status)
                output.print_status(f"  {outcome.task.id} {verdict}")

            try:
                result = await self._agent.run_plan(on_task_start=_start, on_task_end=_end)
            except asyncio.CancelledError:
                output.print_status("● Cancelled.")
                footer.status = "● idle"
                raise
            except Exception as e:
                output.print_error(f"Run-plan error: {e}")
                footer.status = "● error"
                return

            duration = time.monotonic() - start
            done = result.tasks_completed
            failed = sum(1 for o in result.outcomes if o.status == "failed")
            skipped = sum(1 for o in result.outcomes if o.status == "skipped")
            reason = result.stopped_reason
            output.print_turn_summary(
                f"⤷ Run finished: {done} done, {failed} failed, "
                f"{skipped} skipped · stopped: {reason} · {duration:.1f}s"
            )
            footer.status = "● idle"

    def _render_attempt(self, attempt: PatchAttempt) -> str:
        """Card body for one patch attempt: synthesized diff + apply/test
        verdict. Test output is truncated — the full thing is one Ctrl+O
        away via the standard ToolUseCard surface."""
        from code_scalpel.patch.edit_block import edits_to_diff

        diff = edits_to_diff(attempt.edits, self.cwd) if attempt.edits else "(no edits)"
        if attempt.apply_ok:
            verdict = "tests passed" if attempt.tests_passed else "tests failed"
        else:
            verdict = f"apply failed: {attempt.apply_error or 'unknown error'}"
        test_output = attempt.test_output or ""
        if len(test_output) > 2000:
            test_output = test_output[:2000] + "\n… (truncated)"
        parts = [diff, f"--- {verdict} ---"]
        if test_output:
            parts.append(test_output)
        return "\n".join(parts)

    def _record_loop_usage(self, task: str, reply: str, duration: float, attempts: int) -> None:
        """Session bookkeeping for the /loop path.

        Prefers the real usage payload stashed by `_run_first_attempt_streamed`
        (`stream_ask` aggregates provider numbers across rounds). Falls back to
        the char-count heuristic only when the streaming path didn't run or
        the provider didn't include a usage chunk."""
        usage = self._last_stream_usage
        # One-shot — clear so the next /loop call doesn't reuse stale numbers
        # if its stream fails before the UsageReport arrives.
        self._last_stream_usage = None
        if usage is not None:
            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
        else:
            prompt_tokens = len(task) // 4 + 1000
            completion_tokens = len(reply) // 4
        self.session.record(
            ChatResponse(
                content=reply,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=None,
            )
        )
        self._update_ctx()
        summary = _format_turn_summary(
            tool_calls=attempts,
            rate=0.0,
            completion_tokens=completion_tokens,
            duration=duration,
        )
        self.query_one(OutputLog).print_turn_summary(summary)

    async def _regenerate(self, prev_edits: list[Edit]) -> None:
        """Ask the model to retry the patch — used after a rejected or
        failed apply. Builds a context message with what was tried."""
        footer = self.query_one(StatusFooter)
        assert self._agent is not None
        footer.status = "◌ regenerating…"
        from code_scalpel.patch.edit_block import edits_to_diff

        diff = edits_to_diff(prev_edits, self.cwd)
        task = (
            "Your previous patch was rejected or didn't apply. Try a different "
            "approach. Previous attempt:\n\n" + diff
        )
        # debug sub-mode bumps temperature so the retry actually diverges from
        # the original attempt instead of regenerating something near-identical.
        self.run_worker(self._run_step(task, mode="debug"), exclusive=True, group="step")

    async def _wait_mounted(self, widget: Widget) -> None:
        # widget.mount is dispatched via a worker in OutputLog._append.
        # Wait a short tick so update() doesn't race the mount.
        from asyncio import sleep

        for _ in range(20):
            if widget.is_mounted:
                return
            await sleep(0.02)

    async def _remove_progress(self, progress: Widget) -> None:
        """Best-effort removal of the inline turn-progress widget. Tolerates
        the not-yet-mounted race (mount goes through a worker) and a
        double-remove from the success path + an exception handler — we'd
        rather swallow than spam errors in the chat."""
        try:
            if progress.is_mounted:
                await progress.remove()
        except Exception:
            pass

    # ── patch decision ────────────────────────────────────────────────────────

    def on_patch_decision(self, msg: PatchDecision) -> None:
        self.run_worker(self._handle_decision(msg.action), exclusive=True)

    async def _handle_decision(self, action: str) -> None:
        output = self.query_one(OutputLog)
        footer = self.query_one(StatusFooter)

        try:
            card = self.query_one(ToolCallCard)
            await card.remove()
        except Exception:
            pass

        if action == "apply" and self._pending_edits:
            footer.status = "◌ applying…"
            self.state.dirty_patch = True
            self.state.save(self.cwd)
            ok, err = apply_edits(self._pending_edits, self.cwd)
            self._pending_edits = None
            if ok:
                output.print_status("● Patch applied.")
                self.state.dirty_patch = False
                self.state.save(self.cwd)
            else:
                output.print_error(f"Apply failed: {err}")
            footer.status = "● idle"

        elif action == "reject":
            self._pending_edits = None
            output.print_status("Patch rejected.")
            footer.status = "● idle"

        elif action == "regen":
            edits = self._pending_edits
            self._pending_edits = None
            if edits is None or self._agent is None:
                footer.status = "● idle"
            else:
                # Debug retry: feed the apply error back to the model and ask
                # for a fixed patch. One round only — don't spiral.
                self.run_worker(self._regenerate(edits), exclusive=True, group="step")
                return
            footer.status = "● idle"

        self.query_one(ModeInput).focus_input()

    # ── mode cycling ──────────────────────────────────────────────────────────

    def action_cycle_mode(self) -> None:
        self._mode_index = (self._mode_index + 1) % len(self._AGENT_MODES)
        mode = self._AGENT_MODES[self._mode_index]
        self.query_one(ModeInput).set_mode(mode)
        self._update_footer()

    # ── footer helpers ────────────────────────────────────────────────────────

    def _update_footer(self) -> None:
        """Footer is minimal — hints + status + model. Per-turn metrics live
        inline in the chat now (see _format_turn_summary)."""
        footer = self.query_one(StatusFooter)
        footer.hints = r"\[ctrl+t] cycle mode · \[ctrl+q] quit"

    def _update_ctx(self) -> None:
        """Refresh the footer's ctx segment from the current Session +
        state.context_limit. Inline turn summary stops carrying ctx
        because the same number sat in two places and drifted on
        every /compact. Footer is continuous state — typing moves
        the bar, not just turn boundaries."""
        footer = self.query_one(StatusFooter)
        used = self.session.context_used_tokens
        limit = self.state.context_limit
        if not limit:
            footer.ctx = ""
            return
        pct = used / limit * 100
        footer.ctx = f"{used // 1000}k/{limit // 1000}k ({pct:.0f}%)"

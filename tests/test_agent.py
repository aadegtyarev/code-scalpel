from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.agent import StepAgent
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.plan import Task
from tests.mocks import MockLLMAdapter

_EDIT_BLOCK = """\
Here's the fix:

hello.py
```python
<<<<<<< SEARCH
def hello():
    pass
=======
def hello():
    return "hi"
>>>>>>> REPLACE
```
"""

_CONFIG = AppConfig(
    profiles={
        "local": ModelProfile(
            provider="lmstudio",
            model="local-model",
            temperature=0.1,
        )
    },
    # Legacy tests in this module pre-date the read-before-show HOOK and
    # rely on SEARCH/REPLACE blocks going through without an upstream
    # read_file call. Dedicated HOOK tests below opt back in.
    agent=AgentConfig(max_files=2, max_file_lines=50, enforce_read_before_show=False),
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "hello.py").write_text("def hello():\n    pass\n")
    (tmp_path / "main.py").write_text("from hello import hello\nhello()\n")
    return tmp_path


@pytest.mark.asyncio
async def test_ask_extracts_edits(project: Path) -> None:
    llm = MockLLMAdapter([_EDIT_BLOCK])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.ask("make hello return 'hi'")

    assert len(result.edits) == 1
    assert result.edits[0].path == "hello.py"
    assert 'return "hi"' in result.edits[0].replace
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_ask_no_edits_when_plain_text_reply(project: Path) -> None:
    llm = MockLLMAdapter(["Sure, just add a docstring!"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.ask("explain hello")

    assert result.edits == []
    assert result.reply == "Sure, just add a docstring!"


@pytest.mark.asyncio
async def test_ask_sends_system_prompt(project: Path) -> None:
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("do something")

    messages = llm.calls[0]
    assert messages[0]["role"] == "system"
    # New prompt teaches SEARCH/REPLACE, not unified diff
    assert "SEARCH" in messages[0]["content"]


@pytest.mark.asyncio
async def test_system_prompt_carries_identity_anchor(project: Path) -> None:
    """The Identity block guards two distinct failures:
    (1) "кто ты" regressing to "Ты — ассистент…" — weak LLM
        translating the English system prompt back verbatim;
    (2) Identity overreach — answering a short context-question
        ("где сжимается?") with the identity blurb because the
        block tugs too hard. Probe regression 2026-05-11.

    Anchors checked:
    - First-person openings present for both languages.
    - Explicit trigger list AND an "ONLY" / negative-example clause
      so the block can't apply to ambient short questions."""
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("do something")
    system = llm.calls[0][0]["content"]
    assert "Identity" in system
    assert "code-scalpel" in system
    # First-person anchors — without them the model invents English
    # identity blurbs in a Russian conversation and vice versa.
    assert "Я — code-scalpel" in system
    assert "I'm code-scalpel" in system
    # Tight scoping: triggers enumerated, "ONLY" written explicitly.
    # NB: no negative example here. An earlier iteration listed
    # context-shaped questions as "NOT identity" — the model latched
    # onto those examples and started answering legit context
    # questions with "Не понял, переспроси?". Whitelist of triggers
    # beats a blacklist of counterexamples for 14B.
    assert "ONLY" in system
    assert "кто ты" in system
    assert "what are you" in system
    # Anti-example for task-shaped messages — user reported 2026-05-11
    # that "найди место чтобы в футер вывести системное время" got an
    # identity-blurb reply with zero tool calls. The block now names
    # task-words explicitly and tells the model to call tools instead.
    assert "найди" in system or "find" in system.lower()
    assert "list_files" in system or "tools" in system.lower()
    # No "Я — code-scalpel, как помочь?" template — that exact phrase
    # was the bug shape and we ban it specifically.
    assert "NEVER answer" in system or "никогда" in system.lower()


@pytest.mark.asyncio
async def test_ask_sends_system_and_task_only(project: Path) -> None:
    """With native function calling, tools are declared via API schema —
    no need for few-shot examples. Initial messages = system + task."""
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("do something")

    messages = llm.calls[0]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "do something" in messages[1]["content"]


@pytest.mark.asyncio
async def test_ask_user_message_is_just_the_task(project: Path) -> None:
    """User flagged 2026-05-11: 800-1000t of auto-mixed "Project files"
    prefixed every task. Task got buried; short follow-ups got drowned
    in the listing. Fix: user message is ONLY the task — the model
    explores via the `list_files` tool when it actually needs to. No
    Project overview / Project files block, no file paths leaked,
    no symbols."""
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("do something")

    real_task_msg = llm.calls[0][-1]["content"]
    # Just the task. No project listing leaks.
    assert real_task_msg == "do something" or real_task_msg.startswith("do something")
    assert "Project overview" not in real_task_msg
    assert "Project files" not in real_task_msg
    assert "hello.py" not in real_task_msg
    assert "def hello" not in real_task_msg


@pytest.mark.asyncio
async def test_ask_records_response_stats(project: Path) -> None:
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.ask("do something")

    assert result.response.completion_tokens > 0


@pytest.mark.asyncio
async def test_list_files_tool_walks_subdirs(tmp_path: Path) -> None:
    """The list_files tool returns paths from nested directories, not
    just top-level. This is the model's main orientation entry point
    since user_message no longer auto-injects the project listing."""
    from code_scalpel.tools.agent_tools import ToolCall, execute

    (tmp_path / "top.py").write_text("x = 1\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "deep.py").write_text("def f():\n    pass\n")
    (tmp_path / "pkg" / "sub").mkdir()
    (tmp_path / "pkg" / "sub" / "deeper.py").write_text("def g():\n    pass\n")

    call = ToolCall(name="list_files", body="{}")
    result = await execute(call, tmp_path)
    assert result.ok
    out = result.output
    assert "top.py" in out
    assert "pkg/deep.py" in out
    assert "pkg/sub/deeper.py" in out


@pytest.mark.asyncio
async def test_ask_handles_tool_call_loop(project: Path) -> None:
    """Native function calling: model emits structured tool_calls; agent
    executes and appends a tool-role message with the result."""
    from code_scalpel.llm.adapter import NativeToolCall

    tool_call = NativeToolCall(id="call_1", name="read_file", arguments='{"path": "hello.py"}')
    llm = MockLLMAdapter([("", [tool_call]), "Done."])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    result = await agent.ask("look")

    assert result.reply == "Done."
    assert len(llm.calls) == 2
    # The second call must include a tool-role message with the file content
    second_call = llm.calls[1]
    tool_msgs = [m for m in second_call if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_1"
    assert "def hello" in tool_msgs[0]["content"]


@pytest.mark.asyncio
async def test_stream_ask_yields_chunks(project: Path) -> None:
    from code_scalpel.agent import TextDelta

    llm = MockLLMAdapter(["hello"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    items = [c async for c in agent.stream_ask("greet me")]
    text_items = [c for c in items if isinstance(c, TextDelta)]

    assert "".join(c.text for c in text_items) == "hello"
    assert len(text_items) == 5  # per-character stream


@pytest.mark.asyncio
async def test_stream_ask_builds_same_messages_as_ask(project: Path) -> None:
    """Both code paths should construct identical initial messages for the
    same task — history shouldn't sneak into one but not the other."""
    llm = MockLLMAdapter(["X", "X"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first")
    agent.clear_history()  # start fresh so stream_ask sees the same initial state
    async for _ in agent.stream_ask("first"):
        pass

    assert llm.calls[0] == llm.calls[1]


@pytest.mark.asyncio
async def test_history_carries_between_turns(project: Path) -> None:
    """Second ask() sees the first exchange in messages."""
    llm = MockLLMAdapter(["first reply", "second reply"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first task")
    await agent.ask("second task")

    second_call = llm.calls[1]
    contents = [str(m.get("content") or "") for m in second_call]
    joined = "\n".join(contents)
    assert "first task" in joined
    assert "first reply" in joined


@pytest.mark.asyncio
async def test_history_stores_bare_task_not_map(project: Path) -> None:
    """History entries must contain just the user's task, not the bloated
    'Project map:\n...\n\nTask: foo' wrapper. Otherwise every subsequent turn
    duplicates the map in history."""
    llm = MockLLMAdapter(["ok1", "ok2"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first task")

    # The bare task should be what's stored
    assert agent.history[0]["role"] == "user"
    assert agent.history[0]["content"] == "first task"
    assert "Project map" not in agent.history[0]["content"]
    assert agent.history[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_history_grows_with_each_turn(project: Path) -> None:
    llm = MockLLMAdapter(["one", "two", "three"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("a")
    assert len(agent.history) == 2

    await agent.ask("b")
    assert len(agent.history) == 4

    await agent.ask("c")
    assert len(agent.history) == 6


@pytest.mark.asyncio
async def test_ask_default_mode_is_ask_temperature(project: Path) -> None:
    """No explicit mode → defaults to 'ask' temperature (lowest, retrieval)."""
    from code_scalpel.config import ModeTemperatures

    cfg = AppConfig(
        profiles={
            "local": ModelProfile(
                provider="lmstudio",
                model="m",
                temperature=ModeTemperatures(ask=0.1, code=0.7),
            )
        },
        agent=AgentConfig(max_files=2, max_file_lines=50),
    )
    llm = MockLLMAdapter(["plain reply"])
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    await agent.ask("describe hello")

    assert llm.kwargs_calls[0]["temperature"] == 0.1


@pytest.mark.asyncio
async def test_ask_uses_per_mode_temperature(project: Path) -> None:
    from code_scalpel.config import ModeTemperatures

    cfg = AppConfig(
        profiles={
            "local": ModelProfile(
                provider="lmstudio",
                model="m",
                temperature=ModeTemperatures(ask=0.1, plan=0.4, code=0.7, review=0.15, debug=0.9),
            )
        },
        agent=AgentConfig(max_files=2, max_file_lines=50),
    )
    llm = MockLLMAdapter(["a", "b", "c", "d", "e"])
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    await agent.ask("question", mode="ask")
    await agent.ask("plan a feature", mode="plan")
    await agent.ask("write code", mode="code")
    await agent.ask("review patch", mode="review")
    await agent.ask("retry", mode="debug")

    assert llm.kwargs_calls[0]["temperature"] == 0.1
    assert llm.kwargs_calls[1]["temperature"] == 0.4
    assert llm.kwargs_calls[2]["temperature"] == 0.7
    assert llm.kwargs_calls[3]["temperature"] == 0.15
    assert llm.kwargs_calls[4]["temperature"] == 0.9


@pytest.mark.asyncio
async def test_stream_ask_uses_per_mode_temperature(project: Path) -> None:
    from code_scalpel.config import ModeTemperatures

    cfg = AppConfig(
        profiles={
            "local": ModelProfile(
                provider="lmstudio",
                model="m",
                temperature=ModeTemperatures(ask=0.1, code=0.6),
            )
        },
        agent=AgentConfig(max_files=2, max_file_lines=50),
    )
    llm = MockLLMAdapter(["hi"])
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    async for _ in agent.stream_ask("do thing", mode="code"):
        pass

    assert llm.kwargs_calls[0]["temperature"] == 0.6


@pytest.mark.asyncio
async def test_compact_uses_ask_temperature(project: Path) -> None:
    """Compact is summarization — should run at the analytical (ask) temp,
    not whatever mode the user is currently in."""
    from code_scalpel.config import ModeTemperatures

    cfg = AppConfig(
        profiles={
            "local": ModelProfile(
                provider="lmstudio",
                model="m",
                temperature=ModeTemperatures(ask=0.1, code=0.7),
            )
        },
        agent=AgentConfig(max_files=2, max_file_lines=50),
    )
    llm = MockLLMAdapter(["something", "summary bullets"])
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    await agent.ask("primer", mode="code")  # populate history first
    await agent.compact()

    # Two calls total: the code ask and the compact summarization.
    assert llm.kwargs_calls[0]["temperature"] == 0.7  # code ask
    assert llm.kwargs_calls[1]["temperature"] == 0.1  # compact uses ask


@pytest.mark.asyncio
async def test_ask_passes_top_p(project: Path) -> None:
    """top_p is shared across all modes — must show up on every call."""
    llm = MockLLMAdapter(["ok"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("hi")
    assert llm.kwargs_calls[0]["top_p"] == 0.9


@pytest.mark.asyncio
async def test_history_user_messages_are_in_order(project: Path) -> None:
    llm = MockLLMAdapter(["r1", "r2", "r3"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first")
    await agent.ask("second")
    await agent.ask("third")

    user_contents = [m["content"] for m in agent.history if m["role"] == "user"]
    assert user_contents == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_history_visible_to_next_ask_in_correct_role(project: Path) -> None:
    """The previous turn must appear as alternating user/assistant in the next call's
    messages, not as some opaque blob."""
    llm = MockLLMAdapter(["first reply", "second reply"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first")
    await agent.ask("second")

    second_call = llm.calls[1]
    roles = [m["role"] for m in second_call]
    # system, then history pair (user, assistant), then current user
    assert roles == ["system", "user", "assistant", "user"]
    assert second_call[1]["content"] == "first"
    assert second_call[2]["content"] == "first reply"


@pytest.mark.asyncio
async def test_history_records_tool_round_trips(project: Path) -> None:
    """Tool-call round-trips within a turn are persisted into history so
    the next turn sees the full conversation shape (and so the
    compression hook has tool messages to act on). The transcript layout
    is: user task → assistant(tool_calls) → tool result → final assistant."""
    from code_scalpel.llm.adapter import NativeToolCall

    tc = NativeToolCall(id="c1", name="read_file", arguments='{"path": "hello.py"}')
    llm = MockLLMAdapter([("", [tc]), "Final answer."])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("look")

    history = agent.history
    assert len(history) == 4
    assert history[0] == {"role": "user", "content": "look"}
    assert history[1]["role"] == "assistant"
    assert history[1]["tool_calls"][0]["function"]["name"] == "read_file"
    assert history[2]["role"] == "tool"
    assert history[2]["tool_call_id"] == "c1"
    # Final reply.
    assert history[-1] == {"role": "assistant", "content": "Final answer."}


@pytest.mark.asyncio
async def test_clear_history_removes_everything(project: Path) -> None:
    llm = MockLLMAdapter(["r1", "r2"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("a")
    await agent.ask("b")
    assert len(agent.history) == 4
    agent.clear_history()
    assert agent.history == []


@pytest.mark.asyncio
async def test_clear_history_drops_past_turns(project: Path) -> None:
    llm = MockLLMAdapter(["one", "two"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first")
    agent.clear_history()
    await agent.ask("second")

    # Only look at user/assistant messages — the system prompt is a fixed
    # blob that may legitimately contain words like "first" in its rules.
    non_system = [m for m in llm.calls[1] if m.get("role") != "system"]
    second_call_contents = "\n".join(str(m.get("content") or "") for m in non_system)
    assert "first" not in second_call_contents
    assert "second" in second_call_contents


@pytest.mark.asyncio
async def test_compact_summarizes_and_replaces_history(project: Path) -> None:
    llm = MockLLMAdapter(["reply A", "reply B", "- bullet point summary"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("first")
    await agent.ask("second")
    assert len(agent.history) == 4  # 2 user + 2 assistant

    summary = await agent.compact()
    assert summary is not None
    assert "bullet point summary" in summary
    # After compact, history has just the summary message
    assert len(agent.history) == 1
    assert "Summary of the earlier session" in agent.history[0]["content"]


@pytest.mark.asyncio
async def test_system_prompt_allows_text_only_response() -> None:
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT.lower()
    assert "plain text" in text


@pytest.mark.asyncio
async def test_system_prompt_mirrors_user_language() -> None:
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT.lower()
    assert "language" in text and ("same" in text or "user" in text)


@pytest.mark.asyncio
async def test_system_prompt_pins_identity() -> None:
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT.lower()
    assert "code-scalpel" in text
    assert "anthropic" in text and "openai" in text


@pytest.mark.asyncio
async def test_system_prompt_demands_informal_tone() -> None:
    """The user finds the default formal register grating. Prompt must
    explicitly require 'ты' in Russian and discourage corporate hedging."""
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT
    # Russian ты/вы guidance is explicit
    assert '"ты"' in text
    assert '"вы"' in text
    # Forbidden formal phrases should be called out as anti-examples
    assert "Извините" in text
    # Tone keyword anchors the section
    assert "tone" in text.lower()


@pytest.mark.asyncio
async def test_system_prompt_carries_grounding_rules() -> None:
    """Grounding rules are the anti-hallucination clause. They MUST stay in
    the prompt — without them the model invents method names from thin air
    (see the summary_line() regression caught on 2026-05-11)."""
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT.lower()
    assert "grounding" in text
    # Naming must be cross-checked against the MAP
    assert "verify" in text or "does not exist" in text
    # Anti-confabulation rule: similar names don't justify invention
    assert "mark_compacted" in text and "compact" in text
    # Tool descriptions are normative — prompt must direct the model to read
    # them rather than restating the same rules in a competing voice.
    assert "tool" in text and ("description" in text or "normative" in text)
    # Pattern recognition is explicitly rejected as a source of truth.
    assert "pattern recognition" in text or "you might" in text
    # And the dataclass anti-example is in (covers the screenshot bug shape).
    assert "dataclass" in text


@pytest.mark.asyncio
async def test_system_prompt_steers_diagrams_to_mermaid() -> None:
    """When the user asks for a diagram, the model used to emit 5-screen
    ASCII art file trees instead of a proper flowchart (probe
    2026-05-11). The prompt now distinguishes FLOW from STRUCTURE and
    bans ASCII boxes — diagrams ride the Mermaid path which the TUI can
    render inline."""
    from code_scalpel.agent import _SYSTEM_PROMPT

    text = _SYSTEM_PROMPT
    # The directive itself
    assert "Diagrams" in text
    # Mermaid is named as the canonical format
    assert "Mermaid" in text or "mermaid" in text
    # The mermaid fence is shown so the model emits the right shape
    assert "```mermaid" in text
    # ASCII art is explicitly forbidden so the model doesn't fall back
    assert "ASCII" in text and "NEVER" in text
    # Three supported diagram types named so the model picks the right
    # one — flowchart for connections/flow, sequenceDiagram for actors
    # and time, classDiagram for code structure. Other Mermaid types
    # must be steered away from since the inline ASCII renderer doesn't
    # support them.
    assert "flowchart" in text
    assert "sequenceDiagram" in text
    assert "classDiagram" in text


# ── plan mode ───────────────────────────────────────────────────────────────


_PLAN_REPLY = """\
Sure, here's the breakdown.

## T001: Add note model

Goal: Define a Note dataclass with title and body fields.
Files: src/notes.py
Acceptance:
- Note has `title: str` and `body: str` fields
- `__eq__` works by content
Test command: pytest tests/test_notes.py::test_note_model

## T002: Add search function

Goal: Add search_notes(query) that filters notes by title or body.
Files: src/notes.py, tests/test_notes.py
Acceptance:
- Case-insensitive substring match
- Empty query returns all notes
Test command: pytest tests/test_notes.py::test_search
"""


@pytest.mark.asyncio
async def test_plan_mode_addendum_in_system_prompt() -> None:
    """Plan mode appends a planning addendum that asks for TASKS.md output."""
    from code_scalpel.agent import StepAgent

    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(max_files=2, max_file_lines=50),
    )
    llm = MockLLMAdapter(["ok"])
    agent = StepAgent(llm=llm, cwd=Path("."), config=cfg)
    await agent.ask("plan something", mode="plan")
    system = llm.calls[0][0]["content"]
    assert "PLAN mode" in system
    assert "## T001:" in system
    assert "Acceptance:" in system
    # SEARCH/REPLACE explicitly forbidden in plan mode
    assert "NO SEARCH/REPLACE" in system


@pytest.mark.asyncio
async def test_ask_mode_does_not_inject_plan_addendum(project: Path) -> None:
    """The plan-mode addendum must NOT leak into ask/code/review prompts."""
    llm = MockLLMAdapter(["ok"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("question", mode="ask")
    system = llm.calls[0][0]["content"]
    assert "PLAN mode" not in system


@pytest.mark.asyncio
async def test_plan_mode_saves_tasks_md(project: Path) -> None:
    """A reply that contains a `## T001:` plan gets persisted to
    .code-scalpel/TASKS.md — that's the artifact the user (or run mode)
    will execute next."""
    llm = MockLLMAdapter([_PLAN_REPLY])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("plan note search", mode="plan")
    tasks_md = project / ".code-scalpel" / "TASKS.md"
    assert tasks_md.is_file(), "expected TASKS.md to be written"
    text = tasks_md.read_text()
    assert text.startswith("## T001:")
    assert "## T002:" in text
    # Lead-in chatter is stripped
    assert "Sure, here's" not in text


@pytest.mark.asyncio
async def test_plan_mode_skips_save_when_no_tasks_found(project: Path) -> None:
    """If the model asked a clarifying question instead of producing a
    plan, we shouldn't write a junk TASKS.md."""
    llm = MockLLMAdapter(["What kind of search? Title only, or also body?"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("plan", mode="plan")
    assert not (project / ".code-scalpel" / "TASKS.md").exists()


@pytest.mark.asyncio
async def test_ask_mode_does_not_write_tasks_md(project: Path) -> None:
    """Even if an ask-mode reply happens to contain `## T001:` text,
    don't auto-persist — that's plan mode's job."""
    llm = MockLLMAdapter([_PLAN_REPLY])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("question", mode="ask")
    assert not (project / ".code-scalpel" / "TASKS.md").exists()


@pytest.mark.asyncio
async def test_user_message_carries_only_the_task(project: Path) -> None:
    """User message is now ONLY the task verbatim. The previous
    "Task: X\\nProject overview\\n…" layout buried short follow-ups
    under 800-1000 tokens of paths; auto-injection is gone. Model
    explores the project via the `list_files` tool when needed.
    Memory recall stays inline because it's quiet by default."""
    llm = MockLLMAdapter(["first reply", "second reply"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)

    await agent.ask("Sonnet")
    user_msg = llm.calls[0][-1]["content"]
    # The whole user message is the task, no decoration
    assert user_msg.strip() == "Sonnet"


@pytest.mark.asyncio
async def test_user_message_stays_clean_on_every_turn(project: Path) -> None:
    """No "Project files" / "Project overview" block on any turn, ever.
    Multi-turn follow-ups stay tight; model uses list_files to refresh
    its view of the project."""
    llm = MockLLMAdapter(["a", "b", "c"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("first")
    await agent.ask("second")
    await agent.ask("third")
    for i in range(3):
        msg = llm.calls[i][-1]["content"]
        assert "Project overview" not in msg
        assert "Project files" not in msg
        assert "hello.py" not in msg


@pytest.mark.asyncio
async def test_stream_ask_in_plan_mode_also_saves(project: Path) -> None:
    """TUI uses stream_ask, not ask. The plan-saving hook must fire from
    the streaming path too."""
    llm = MockLLMAdapter([_PLAN_REPLY])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    async for _ in agent.stream_ask("plan", mode="plan"):
        pass
    assert (project / ".code-scalpel" / "TASKS.md").is_file()


# ── loop guard (force-answer when the model spins on identical tool calls) ──


@pytest.mark.asyncio
async def test_loop_guard_breaks_repeating_tool_calls(project: Path) -> None:
    """If the model emits the SAME tool call twice in a row, the agent
    injects a force-answer message instead of executing again. Otherwise
    a buggy model could loop forever (or until _MAX_TOOL_ROUNDS). The
    guard fires on the second occurrence and the third turn produces
    the final text answer."""
    from code_scalpel.llm.adapter import NativeToolCall

    repeated = NativeToolCall(id="c1", name="read_file", arguments='{"path": "hello.py"}')
    # Round 1: tool_call. Round 2: same tool_call → triggers guard.
    # Round 3: plain text answer.
    llm = MockLLMAdapter(
        [
            ("", [repeated]),
            ("", [repeated]),
            "Final answer based on what I had.",
        ]
    )
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    result = await agent.ask("look")
    assert result.reply == "Final answer based on what I had."
    # Three chat() calls — last one received the force-answer prompt.
    assert len(llm.calls) == 3
    third_call = llm.calls[2]
    contents = "\n".join(str(m.get("content") or "") for m in third_call)
    assert "Stop calling" in contents or "answer the original question" in contents


@pytest.mark.asyncio
async def test_loop_guard_works_in_stream_path(project: Path) -> None:
    """Same guard, exercised through stream_ask — TUI's actual path."""
    from code_scalpel.llm.adapter import NativeToolCall

    repeated = NativeToolCall(id="c1", name="read_file", arguments='{"path": "hello.py"}')
    llm = MockLLMAdapter(
        [
            ("", [repeated]),
            ("", [repeated]),
            "Done.",
        ]
    )
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    chunks: list[str] = []
    async for item in agent.stream_ask("look"):
        from code_scalpel.agent import TextDelta

        if isinstance(item, TextDelta):
            chunks.append(item.text)
    assert "".join(chunks).endswith("Done.")
    # Force-answer reached the third call
    assert len(llm.calls) == 3


# ── iterative patch loop (code_with_retry) ──────────────────────────────────


_BAD_PATCH = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    pass
=======
def hello():
    return "wrong"
>>>>>>> REPLACE
```
"""

_GOOD_PATCH = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    return "wrong"
=======
def hello():
    return "hi"
>>>>>>> REPLACE
```
"""

# Direct fix from the pristine `pass` body (used when round 1 didn't change
# the file because its SEARCH didn't match).
_GOOD_PATCH_FROM_ORIGINAL = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    pass
=======
def hello():
    return "hi"
>>>>>>> REPLACE
```
"""


def _retry_config(*, max_debug_attempts: int = 2) -> AppConfig:
    return AppConfig(
        profiles={
            "local": ModelProfile(
                provider="lmstudio",
                model="local-model",
                temperature=0.1,
            )
        },
        agent=AgentConfig(
            max_files=2,
            max_file_lines=50,
            max_debug_attempts=max_debug_attempts,
            iterative_patch_loop=True,
            # Retry-loop tests pre-date the HOOK and feed canned patches
            # straight through. Dedicated HOOK tests opt back in.
            enforce_read_before_show=False,
        ),
    )


@pytest.mark.asyncio
async def test_code_with_retry_fixes_failing_test(project: Path) -> None:
    """Round 1: bad patch applies but tests fail. Round 2: model receives the
    test output as context, emits the good patch, tests pass, return."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    llm = MockLLMAdapter([_BAD_PATCH, _GOOD_PATCH])
    shell = MockShellRunner(
        [
            ShellResult("FAILED tests/test_hello.py::test_hello - assert 'wrong' == 'hi'", 1),
            ShellResult("1 passed", 0),
        ]
    )
    agent = StepAgent(llm=llm, cwd=project, config=_retry_config(), shell_runner=shell)

    result = await agent.code_with_retry("make hello return 'hi'")

    assert len(result.attempts) == 2
    assert result.attempts[0].apply_ok is True
    assert result.attempts[0].tests_passed is False
    assert "wrong" in result.attempts[0].test_output
    assert result.attempts[1].tests_passed is True
    # Final patch is on disk — edits cleared so caller doesn't re-apply.
    assert result.edits == []
    # File on disk reflects the good patch
    assert 'return "hi"' in (project / "hello.py").read_text()
    # Two model calls — the retry got the test output as context
    assert len(llm.calls) == 2
    second_task = llm.calls[1][-1]["content"]
    assert "test suite is now red" in second_task or "test" in second_task.lower()
    assert "wrong" in second_task  # the failure output got fed back


@pytest.mark.asyncio
async def test_code_with_retry_rolls_back_workspace_on_exhaustion(project: Path) -> None:
    """After all retries fail, the workspace must be restored to the
    pre-loop state. Without rollback, N successive patches would land
    on disk and the user could only [r]eject the LAST visible diff —
    earlier mutations would persist silently. Code-review bug from
    the 12-commit session audit."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    original_text = (project / "hello.py").read_text()
    bad_patch_self_idempotent = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    return "wrong"
=======
def hello():
    return "wrong"
>>>>>>> REPLACE
```
"""
    llm = MockLLMAdapter(
        [_BAD_PATCH, bad_patch_self_idempotent, bad_patch_self_idempotent, _BAD_PATCH]
    )
    shell = MockShellRunner([ShellResult("still failing", 1)] * 5)
    agent = StepAgent(
        llm=llm,
        cwd=project,
        config=_retry_config(max_debug_attempts=2),
        shell_runner=shell,
    )

    await agent.code_with_retry("fix something impossible")

    # Workspace returned to its pre-loop state — no cumulative damage.
    assert (project / "hello.py").read_text() == original_text


@pytest.mark.asyncio
async def test_code_with_retry_rollback_removes_newly_created_files(project: Path) -> None:
    """If a retry attempt created a file from scratch (empty SEARCH),
    the rollback must delete it — otherwise the workspace ends up with
    half-finished scaffolding the user didn't ask to keep."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    new_file_patch = """\
new_module.py
```python
<<<<<<< SEARCH
=======
def stub():
    pass
>>>>>>> REPLACE
```
"""
    # All attempts produce a new file then run_tests fails.
    llm = MockLLMAdapter([new_file_patch] * 3)
    shell = MockShellRunner([ShellResult("FAIL", 1)] * 3)
    agent = StepAgent(
        llm=llm,
        cwd=project,
        config=_retry_config(max_debug_attempts=2),
        shell_runner=shell,
    )

    await agent.code_with_retry("create a module")

    assert not (project / "new_module.py").exists(), (
        "new file from a failed loop must be deleted by rollback"
    )


@pytest.mark.asyncio
async def test_code_with_retry_stops_at_max_attempts(project: Path) -> None:
    """Model never produces a passing patch. After max_debug_attempts retries
    (so 1 + N total calls) we stop and return the last attempt."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    # Each round the model emits a patch that's a no-op rewrite of itself
    # (`return "wrong"` → `return "wrong"`). The first round mutates the
    # file; rounds 2 and 3 re-emit the same patch which keeps applying
    # because SEARCH still matches. Tests fail every time.
    bad_patch_self_idempotent = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    return "wrong"
=======
def hello():
    return "wrong"
>>>>>>> REPLACE
```
"""
    llm = MockLLMAdapter(
        [_BAD_PATCH, bad_patch_self_idempotent, bad_patch_self_idempotent, _BAD_PATCH]
    )
    shell = MockShellRunner([ShellResult("still failing", 1)] * 5)
    agent = StepAgent(
        llm=llm,
        cwd=project,
        config=_retry_config(max_debug_attempts=2),
        shell_runner=shell,
    )

    result = await agent.code_with_retry("fix something impossible")

    assert len(result.attempts) == 3  # initial + 2 retries
    assert all(not a.tests_passed for a in result.attempts)
    # Last attempt's edits remain on the result so the TUI can show them
    assert result.edits, "exhausted-retries case must surface the last patch"
    assert len(llm.calls) == 3
    # We invoked run_tests once per attempt (3 times), because all 3 patches
    # applied cleanly and only the tests rejected them.
    pytest_calls = [c for c in shell.calls if c and c[0] == "pytest"]
    assert len(pytest_calls) == 3


@pytest.mark.asyncio
async def test_code_with_retry_disabled_flag_falls_back_to_ask(project: Path) -> None:
    """When iterative_patch_loop=False, code_with_retry is a pass-through to
    ask() — no tests run, no auto-retry, existing behavior preserved."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(
            max_files=2,
            max_file_lines=50,
            iterative_patch_loop=False,  # off — opt-in
            enforce_read_before_show=False,
        ),
    )
    llm = MockLLMAdapter([_BAD_PATCH])
    shell = MockShellRunner([ShellResult("would-be tests", 1)])
    agent = StepAgent(llm=llm, cwd=project, config=cfg, shell_runner=shell)

    result = await agent.code_with_retry("just apply once")

    # No retries recorded — we went through the regular ask path.
    assert result.attempts == ()
    # Edits surfaced as the regular ask result (caller applies, not us).
    assert len(result.edits) == 1
    # Only one model call, no pytest invocations.
    assert len(llm.calls) == 1
    assert not any(c and c[0] == "pytest" for c in shell.calls)


@pytest.mark.asyncio
async def test_code_with_retry_no_edits_returns_immediately(project: Path) -> None:
    """If the model replies in plain text (no SEARCH/REPLACE), there's nothing
    to apply and nothing to retry — return on the first attempt without
    running tests."""
    from tests.mocks import MockShellRunner

    llm = MockLLMAdapter(["No changes needed — the file already does that."])
    shell = MockShellRunner([])
    agent = StepAgent(llm=llm, cwd=project, config=_retry_config(), shell_runner=shell)

    result = await agent.code_with_retry("what do you think?")

    assert result.attempts == ()
    assert result.edits == []
    assert shell.calls == []
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_code_with_retry_records_apply_failure(project: Path) -> None:
    """When the patch does NOT apply (SEARCH text doesn't match), we record
    the apply error and feed it back to the model for retry — without trying
    to run tests on a half-applied tree."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    no_match_patch = """\
hello.py
```python
<<<<<<< SEARCH
def nonexistent():
    return 42
=======
def replaced():
    return 1
>>>>>>> REPLACE
```
"""
    llm = MockLLMAdapter([no_match_patch, _GOOD_PATCH_FROM_ORIGINAL])
    shell = MockShellRunner([ShellResult("1 passed", 0)])
    agent = StepAgent(llm=llm, cwd=project, config=_retry_config(), shell_runner=shell)

    result = await agent.code_with_retry("make hello return 'hi'")

    assert len(result.attempts) == 2
    assert result.attempts[0].apply_ok is False
    assert result.attempts[0].apply_error  # non-empty
    assert result.attempts[0].test_output == ""  # tests not run
    assert result.attempts[1].apply_ok is True
    assert result.attempts[1].tests_passed is True
    # The retry prompt mentions the apply error
    second_task = llm.calls[1][-1]["content"]
    assert "did not apply" in second_task or "apply" in second_task.lower()


# ── memory recall integration ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_message_carries_recalled_notes_when_memory_hits(project: Path) -> None:
    """When MemoryStore is wired in and the user's task matches an entry,
    that note must appear inline in the user message under a clearly
    labelled "Recalled notes" header — that's the whole reason the
    recall layer exists. No header = no signal for the model that the
    bullet came from memory, not from the user."""
    from code_scalpel.memory import MemoryStore

    mem = MemoryStore(root=project)
    mem.add("Always run ruff format before commit")
    mem.add("Tests must hit a real database, never mocks")

    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG, memory=mem)
    await agent.ask("what to do before commit?")

    user_msg = llm.calls[0][-1]["content"]
    assert "Recalled notes" in user_msg
    assert "ruff format" in user_msg


@pytest.mark.asyncio
async def test_user_message_no_memory_header_when_store_empty(project: Path) -> None:
    """Empty store → no "Recalled notes" header. Weak models latch onto
    visible headers and try to explain them; an empty one is pure noise."""
    from code_scalpel.memory import MemoryStore

    mem = MemoryStore(root=project)  # empty
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG, memory=mem)
    await agent.ask("any task")

    user_msg = llm.calls[0][-1]["content"]
    assert "Recalled notes" not in user_msg


@pytest.mark.asyncio
async def test_user_message_no_memory_header_when_store_not_wired(project: Path) -> None:
    """memory=None (default) → recall is fully disabled. Important for
    tests and lightweight callers that never want to materialise a
    .code-scalpel/memory.db file."""
    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(llm=llm, cwd=project, config=_CONFIG)
    await agent.ask("any task")

    user_msg = llm.calls[0][-1]["content"]
    assert "Recalled notes" not in user_msg


@pytest.mark.asyncio
async def test_user_message_survives_broken_memory_query(project: Path) -> None:
    """A malformed FTS5 query inside the recall call must NOT break the
    turn. Memory is a convenience layer; the turn always wins. We
    simulate the failure with a stub store whose .search raises."""

    class _BrokenStore:
        def search(self, q: str, *, k: int = 3) -> list[object]:  # noqa: ARG002
            raise RuntimeError("simulated FTS5 failure")

    llm = MockLLMAdapter(["OK"])
    agent = StepAgent(
        llm=llm,
        cwd=project,
        config=_CONFIG,
        memory=_BrokenStore(),  # type: ignore[arg-type]
    )
    await agent.ask("any task")
    # No header, but the call completed normally.
    assert llm.calls


# ── supervised autonomous mode (run_plan) ───────────────────────────────────

_TASKS_THREE = (
    "## T001: Make hello return hi\n\n"
    "Goal: change return value\n"
    "Files: hello.py\n"
    "Acceptance:\n"
    "- hello() returns 'hi'\n"
    "Test command: pytest\n\n"
    "## T002: Touch main\n\n"
    "Goal: keep import working\n"
    "Files: main.py\n"
    "Acceptance:\n"
    "- imports cleanly\n"
    "Test command: pytest\n\n"
    "## T003: Tidy up\n\n"
    "Goal: docstring\n"
    "Files: hello.py\n"
    "Acceptance:\n"
    "- has docstring\n"
    "Test command: pytest\n"
)


def _write_tasks(project: Path, text: str) -> Path:
    p = project / ".code-scalpel" / "TASKS.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


_GOOD_PATCH_NOOP = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    pass
=======
def hello():
    return "hi"
>>>>>>> REPLACE
```
"""


@pytest.mark.asyncio
async def test_run_plan_happy_path_marks_each_task_done(project: Path) -> None:
    """All three tasks succeed → file gets three [✓] marks and outcomes
    list mirrors the order."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    tasks_path = _write_tasks(project, _TASKS_THREE)

    # Three patches, three pytest passes — one per task. After T001 the
    # file is already changed, so T002/T003 use plain-text "no-op" replies
    # (skipped, won't fail). To keep this simple we have all three
    # produce a benign patch + passing tests.
    edit_main = """\
main.py
```python
<<<<<<< SEARCH
from hello import hello
hello()
=======
from hello import hello

hello()
>>>>>>> REPLACE
```
"""
    edit_doc = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    return "hi"
=======
def hello():
    \"\"\"Greet.\"\"\"
    return "hi"
>>>>>>> REPLACE
```
"""
    llm = MockLLMAdapter([_GOOD_PATCH_NOOP, edit_main, edit_doc])
    shell = MockShellRunner([ShellResult("1 passed", 0)] * 3)
    agent = StepAgent(llm=llm, cwd=project, config=_retry_config(), shell_runner=shell)

    result = await agent.run_plan()

    assert result.stopped_reason == "all_done"
    assert result.tasks_completed == 3
    assert len(result.outcomes) == 3
    assert [o.status for o in result.outcomes] == ["done", "done", "done"]
    # File now carries three [✓] heads.
    final = tasks_path.read_text()
    assert final.count("## [✓] T") == 3


@pytest.mark.asyncio
async def test_run_plan_stops_after_consecutive_failures(project: Path) -> None:
    """Two consecutive failed tasks → stop with reason `max_failures`."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    _write_tasks(project, _TASKS_THREE)

    # All patches produce edits that apply but tests fail. Each task
    # consumes (max_debug_attempts + 1) = 3 LLM responses and pytest
    # invocations. We feed bad patches for the first two tasks → both
    # fail → stop_after_failures=2 trips on the second.
    bad = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    pass
=======
def hello():
    return "wrong"
>>>>>>> REPLACE
```
"""
    bad_idem = """\
hello.py
```python
<<<<<<< SEARCH
def hello():
    return "wrong"
=======
def hello():
    return "wrong"
>>>>>>> REPLACE
```
"""
    llm = MockLLMAdapter([bad, bad_idem, bad_idem] * 2)
    shell = MockShellRunner([ShellResult("FAILED", 1)] * 10)
    agent = StepAgent(llm=llm, cwd=project, config=_retry_config(), shell_runner=shell)

    result = await agent.run_plan(stop_after_failures=2)

    assert result.stopped_reason == "max_failures"
    assert result.tasks_completed == 0
    # Two outcomes (both failed); T003 never started.
    assert len(result.outcomes) == 2
    assert all(o.status == "failed" for o in result.outcomes)


@pytest.mark.asyncio
async def test_run_plan_no_tasks_file_returns_no_tasks(project: Path) -> None:
    """File missing → reason `no_tasks`, no exception. The TUI uses this
    to coach the user to switch into plan mode first."""
    llm = MockLLMAdapter([])
    agent = StepAgent(llm=llm, cwd=project, config=_retry_config())

    result = await agent.run_plan()

    assert result.stopped_reason == "no_tasks"
    assert result.outcomes == ()
    assert result.tasks_completed == 0
    # Never called the LLM.
    assert llm.calls == []


@pytest.mark.asyncio
async def test_run_plan_all_done_returns_immediately(project: Path) -> None:
    """A file where every task is already [✓] is a no-op."""
    _write_tasks(
        project,
        "## [✓] T001: done\n\nGoal: x\n\n## [✓] T002: also done\n\nGoal: y\n",
    )
    llm = MockLLMAdapter([])
    agent = StepAgent(llm=llm, cwd=project, config=_retry_config())

    result = await agent.run_plan()

    assert result.stopped_reason == "all_done"
    assert result.tasks_completed == 0
    assert llm.calls == []


@pytest.mark.asyncio
async def test_run_plan_detects_plan_modification_mid_run(project: Path) -> None:
    """If TASKS.md changes between iterations (user edited it in another
    window), stop with reason `plan_modified`. Already-marked progress
    stays on disk; the user's edits win the race."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    tasks_path = _write_tasks(project, _TASKS_THREE)

    # First task succeeds. Hook before second task starts overwrites
    # TASKS.md with foreign content to simulate concurrent edit.
    called = {"n": 0}

    def _meddle(task: Task) -> None:
        called["n"] += 1
        if called["n"] == 2:
            tasks_path.write_text("## T999: foreign\n\nGoal: meddled\n")

    edit_main = """\
main.py
```python
<<<<<<< SEARCH
from hello import hello
hello()
=======
from hello import hello

hello()
>>>>>>> REPLACE
```
"""
    llm = MockLLMAdapter([_GOOD_PATCH_NOOP, edit_main])
    shell = MockShellRunner([ShellResult("1 passed", 0)] * 2)
    agent = StepAgent(llm=llm, cwd=project, config=_retry_config(), shell_runner=shell)

    result = await agent.run_plan(on_task_start=_meddle)

    assert result.stopped_reason == "plan_modified"
    assert result.tasks_completed == 1
    # The user's hand-rewrite is what's on disk; we did NOT clobber it.
    assert "foreign" in tasks_path.read_text()


@pytest.mark.asyncio
async def test_run_plan_skipped_when_model_emits_no_edits(project: Path) -> None:
    """Model replies in plain text for a task — that task is `skipped`,
    not `failed`. The skip doesn't count toward the failure budget."""
    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    _write_tasks(
        project,
        "## T001: clarify\n\nGoal: figure it out\n\n"
        "## T002: do it\n\nGoal: actually patch\nFiles: hello.py\n",
    )

    # T001 → plain text. T002 → working patch.
    llm = MockLLMAdapter(
        [
            "I have a question about what 'figure it out' means here.",
            _GOOD_PATCH_NOOP,
        ]
    )
    shell = MockShellRunner([ShellResult("1 passed", 0)])
    agent = StepAgent(llm=llm, cwd=project, config=_retry_config(), shell_runner=shell)

    result = await agent.run_plan(stop_after_failures=2)

    assert result.stopped_reason == "all_done"
    assert [o.status for o in result.outcomes] == ["skipped", "done"]
    assert result.tasks_completed == 1


@pytest.mark.asyncio
async def test_run_plan_cancellation_propagates_and_keeps_done_marks(
    project: Path,
) -> None:
    """If `asyncio.CancelledError` fires mid-run (user pressed Esc), the
    error must propagate. Tasks already marked [✓] stay on disk."""
    import asyncio as _asyncio

    from code_scalpel.tools.shell import ShellResult
    from tests.mocks import MockShellRunner

    tasks_path = _write_tasks(project, _TASKS_THREE)

    # T001 succeeds. T002 raises CancelledError as the user hits Esc
    # mid-run. We simulate that by patching code_with_retry on the
    # agent to raise on its second call.
    edit_main = """\
main.py
```python
<<<<<<< SEARCH
from hello import hello
hello()
=======
from hello import hello

hello()
>>>>>>> REPLACE
```
"""
    llm = MockLLMAdapter([_GOOD_PATCH_NOOP, edit_main])
    shell = MockShellRunner([ShellResult("1 passed", 0)])
    agent = StepAgent(llm=llm, cwd=project, config=_retry_config(), shell_runner=shell)

    original = agent.code_with_retry
    call_count = {"n": 0}

    async def _cancelling_wrapper(task: str, *, mode: str = "code"):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise _asyncio.CancelledError()
        return await original(task, mode=mode)

    agent.code_with_retry = _cancelling_wrapper  # type: ignore[method-assign]

    with pytest.raises(_asyncio.CancelledError):
        await agent.run_plan()

    # T001's [✓] mark survived the cancel.
    assert "[✓] T001" in tasks_path.read_text()


# ── enforce-read-before-show HOOK ──────────────────────────────────────────

_HOOK_CONFIG = AppConfig(
    profiles={
        "local": ModelProfile(
            provider="lmstudio",
            model="local-model",
            temperature=0.1,
        )
    },
    agent=AgentConfig(max_files=2, max_file_lines=50, enforce_read_before_show=True),
)


@pytest.mark.asyncio
async def test_hook_fires_when_patch_emitted_without_read(project: Path) -> None:
    """Model dumps a SEARCH/REPLACE block targeting hello.py without ever
    calling read_file. The HOOK rejects the first reply, sends a re-prompt
    user-message, and the second reply is what we return."""
    llm = MockLLMAdapter([_EDIT_BLOCK, "Now I read it: " + _EDIT_BLOCK])
    agent = StepAgent(llm=llm, cwd=project, config=_HOOK_CONFIG)

    result = await agent.ask("change hello to return hi")

    # Two model calls — the second carries the re-prompt.
    assert len(llm.calls) == 2
    second_user = llm.calls[1][-1]["content"]
    assert "read_file" in second_user and "hello.py" in second_user
    # We returned the second reply, not the first.
    assert "Now I read it" in result.reply
    assert result.edits, "second reply still carried a SEARCH/REPLACE block"


@pytest.mark.asyncio
async def test_hook_does_not_fire_when_read_file_was_called_this_turn(
    project: Path,
) -> None:
    """Model called read_file(hello.py) first, then emitted a patch. HOOK
    has its grounding signal — no re-prompt."""
    from code_scalpel.llm.adapter import NativeToolCall

    tc = NativeToolCall(id="c1", name="read_file", arguments='{"path": "hello.py"}')
    llm = MockLLMAdapter([("", [tc]), _EDIT_BLOCK])
    agent = StepAgent(llm=llm, cwd=project, config=_HOOK_CONFIG)

    result = await agent.ask("change hello")

    # Two model calls — both inside the original chat loop (the tool round
    # and the final reply). No HOOK retry.
    assert len(llm.calls) == 2
    assert result.edits
    # The bare task is in history, not the re-prompt — proving HOOK didn't
    # rewind and re-ask.
    assert agent.history[0]["content"] == "change hello"


@pytest.mark.asyncio
async def test_hook_does_not_fire_when_read_file_was_called_previous_turn(
    project: Path,
) -> None:
    """Turn 1 reads hello.py. Turn 2 emits a patch without re-reading —
    HOOK must accept because the read is in the cross-turn record."""
    from code_scalpel.llm.adapter import NativeToolCall

    tc = NativeToolCall(id="c1", name="read_file", arguments='{"path": "hello.py"}')
    # Turn 1: tool_call → plain text.
    # Turn 2: patch directly.
    llm = MockLLMAdapter([("", [tc]), "Read it, here you go.", _EDIT_BLOCK])
    agent = StepAgent(llm=llm, cwd=project, config=_HOOK_CONFIG)

    await agent.ask("read hello and tell me about it")
    result = await agent.ask("now change it to return hi")

    # Turn 1 = 2 calls (tool + reply), turn 2 = 1 call (no HOOK retry).
    assert len(llm.calls) == 3
    assert result.edits


@pytest.mark.asyncio
async def test_hook_does_not_fire_on_plain_prose_reply(project: Path) -> None:
    """No code block in the reply → pass-through, regardless of reads."""
    llm = MockLLMAdapter(["Sure, hello.py looks fine to me."])
    agent = StepAgent(llm=llm, cwd=project, config=_HOOK_CONFIG)

    result = await agent.ask("anything to worry about in hello.py?")

    assert len(llm.calls) == 1
    assert result.reply == "Sure, hello.py looks fine to me."


@pytest.mark.asyncio
async def test_hook_disabled_by_config(project: Path) -> None:
    """enforce_read_before_show=False → HOOK never fires even on the worst
    fabricated-patch case."""
    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(max_files=2, max_file_lines=50, enforce_read_before_show=False),
    )
    llm = MockLLMAdapter([_EDIT_BLOCK])
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    result = await agent.ask("change hello")

    assert len(llm.calls) == 1
    assert result.edits


@pytest.mark.asyncio
async def test_hook_caps_at_one_retry(project: Path) -> None:
    """Model re-emits an unread SEARCH/REPLACE block on the re-prompt
    too. HOOK does NOT re-fire — we accept the second reply, even though
    it's still ungrounded. No infinite loop."""
    llm = MockLLMAdapter([_EDIT_BLOCK, _EDIT_BLOCK, _EDIT_BLOCK])
    agent = StepAgent(llm=llm, cwd=project, config=_HOOK_CONFIG)

    result = await agent.ask("change hello")

    # Exactly two model calls — initial + one re-prompt. NOT three.
    assert len(llm.calls) == 2
    assert result.edits


@pytest.mark.asyncio
async def test_hook_re_prompt_mentions_target_path(project: Path) -> None:
    """The re-prompt cites the specific path the model fabricated against,
    so the model can read EXACTLY that file rather than guess which one
    needed grounding."""
    multi_file_block = """\
pkg/deep.py
```python
<<<<<<< SEARCH
def f():
    pass
=======
def f():
    return 1
>>>>>>> REPLACE
```
"""
    (project / "pkg").mkdir(exist_ok=True)
    (project / "pkg" / "deep.py").write_text("def f():\n    pass\n")

    llm = MockLLMAdapter([multi_file_block, "OK done."])
    agent = StepAgent(llm=llm, cwd=project, config=_HOOK_CONFIG)

    await agent.ask("fix f")

    second_user = llm.calls[1][-1]["content"]
    assert "pkg/deep.py" in second_user


@pytest.mark.asyncio
async def test_hook_fires_on_bare_python_fence_when_task_names_file(
    project: Path,
) -> None:
    """Reply has plain ```python fenced body (no SEARCH/REPLACE) for a
    file the user named — HOOK still fires. This catches `test_qwen_reads
    _file_even_for_vague_show_code`-style failures where the model
    fabricates a method body from training-data shape."""
    fake_body = '```python\ndef hello():\n    return "fabricated"\n```\n'
    llm = MockLLMAdapter([fake_body, "OK I'll read it first."])
    agent = StepAgent(llm=llm, cwd=project, config=_HOOK_CONFIG)

    await agent.ask("show me the code in hello.py")

    assert len(llm.calls) == 2
    second_user = llm.calls[1][-1]["content"]
    assert "hello.py" in second_user


@pytest.mark.asyncio
async def test_hook_does_not_fire_on_bare_python_fence_when_task_is_generic(
    project: Path,
) -> None:
    """Reply has a ```python fence but the user's task doesn't name a
    project file — conversational example code, HOOK stays silent."""
    example = "Sure, a list comp:\n```python\n[x for x in items if x]\n```\n"
    llm = MockLLMAdapter([example])
    agent = StepAgent(llm=llm, cwd=project, config=_HOOK_CONFIG)

    result = await agent.ask("how would I write a list comprehension?")

    assert len(llm.calls) == 1
    assert "list comp" in result.reply


# --- Tool-result compression hook -------------------------------------------
#
# These tests exercise the cross-turn compression pass: when a tool
# message in `agent.history` is old enough (turn-age > threshold) AND
# long enough (content >= min_chars), the hook rewrites its content
# with a one-line marker. Recent / short / non-tool messages stay
# untouched. The toggle on AgentConfig must disable the pass entirely.

_COMPRESS_CONFIG = AppConfig(
    profiles={"local": ModelProfile(provider="lmstudio", model="m")},
    agent=AgentConfig(
        max_files=2,
        max_file_lines=50,
        enforce_read_before_show=False,
        compress_tool_results=True,
        compress_tool_results_after_turns=1,
        compress_tool_results_min_chars=50,
    ),
)


@pytest.mark.asyncio
async def test_compress_rewrites_old_long_tool_result(project: Path) -> None:
    """Turn 1: model reads hello.py (long output). Turn 2+: that result
    is older than the threshold and longer than min_chars — replaced
    with a marker. Round-trip shape (tool role, tool_call_id) stays
    intact so the model still sees a valid conversation."""
    from code_scalpel.llm.adapter import NativeToolCall

    tc = NativeToolCall(id="c1", name="read_file", arguments='{"path": "hello.py"}')
    # Long tool output: we mock-trigger by making hello.py larger.
    big_body = "def hello():\n" + "    x = 1  # padding line\n" * 100
    (project / "hello.py").write_text(big_body)

    llm = MockLLMAdapter([("", [tc]), "read it", "follow up", "third"])
    agent = StepAgent(llm=llm, cwd=project, config=_COMPRESS_CONFIG)

    await agent.ask("read hello")  # turn 0 — produces a tool message
    # Sanity: the tool result is currently a raw long blob.
    tool_msg = next(m for m in agent.history if m.get("role") == "tool")
    assert "padding line" in tool_msg["content"]
    assert len(tool_msg["content"]) > 200

    await agent.ask("anything else?")  # turn 1 — still recent, must NOT compress
    tool_msg = next(m for m in agent.history if m.get("role") == "tool")
    assert "padding line" in tool_msg["content"]

    await agent.ask("third question")  # turn 2 — age > threshold, fire
    tool_msg = next(m for m in agent.history if m.get("role") == "tool")
    assert tool_msg["content"].startswith("[compressed:")
    assert "read_file(path=hello.py)" in tool_msg["content"]
    assert "see turn 0" in tool_msg["content"]
    # Round-trip shape preserved.
    assert tool_msg["tool_call_id"] == "c1"


@pytest.mark.asyncio
async def test_compress_leaves_recent_tool_result_untouched(project: Path) -> None:
    """A tool result from the just-completed turn (age 0) is still
    actively load-bearing — must NOT be rewritten on the next turn."""
    from code_scalpel.llm.adapter import NativeToolCall

    tc = NativeToolCall(id="c1", name="read_file", arguments='{"path": "hello.py"}')
    big_body = "def hello():\n" + "    x = 1  # padding line\n" * 100
    (project / "hello.py").write_text(big_body)

    llm = MockLLMAdapter([("", [tc]), "read it", "follow up"])
    agent = StepAgent(llm=llm, cwd=project, config=_COMPRESS_CONFIG)

    await agent.ask("read hello")  # turn 0
    await agent.ask("anything else?")  # turn 1 — age = 1, not yet > threshold (=1)

    tool_msg = next(m for m in agent.history if m.get("role") == "tool")
    assert "padding line" in tool_msg["content"]
    assert not tool_msg["content"].startswith("[compressed:")


@pytest.mark.asyncio
async def test_compress_leaves_short_tool_result_untouched(project: Path) -> None:
    """A 20-byte run_tests verdict ("0 failed, 12 passed") is shorter
    than its replacement marker would be. Compression must respect the
    `min_chars` floor regardless of age."""
    from code_scalpel.llm.adapter import NativeToolCall

    tc = NativeToolCall(id="c1", name="read_file", arguments='{"path": "hello.py"}')
    # Default project fixture hello.py is ~22 bytes — well below the 50-char min.
    llm = MockLLMAdapter([("", [tc]), "read it", "more", "more again", "yet more"])
    agent = StepAgent(llm=llm, cwd=project, config=_COMPRESS_CONFIG)

    await agent.ask("read hello")  # turn 0
    await agent.ask("two")
    await agent.ask("three")
    await agent.ask("four")  # plenty of age now

    tool_msg = next(m for m in agent.history if m.get("role") == "tool")
    # Short payload — survives every compression pass.
    assert not tool_msg["content"].startswith("[compressed:")
    assert "def hello" in tool_msg["content"]


@pytest.mark.asyncio
async def test_compress_disabled_by_config(project: Path) -> None:
    """compress_tool_results=False short-circuits the entire pass —
    long old tool results stay verbatim, the marker is never built."""
    from code_scalpel.llm.adapter import NativeToolCall

    cfg = AppConfig(
        profiles={"local": ModelProfile(provider="lmstudio", model="m")},
        agent=AgentConfig(
            max_files=2,
            max_file_lines=50,
            enforce_read_before_show=False,
            compress_tool_results=False,  # the switch
            compress_tool_results_after_turns=1,
            compress_tool_results_min_chars=50,
        ),
    )

    tc = NativeToolCall(id="c1", name="read_file", arguments='{"path": "hello.py"}')
    big_body = "def hello():\n" + "    x = 1  # padding line\n" * 100
    (project / "hello.py").write_text(big_body)

    llm = MockLLMAdapter([("", [tc]), "read it", "f1", "f2", "f3"])
    agent = StepAgent(llm=llm, cwd=project, config=cfg)

    await agent.ask("read hello")
    await agent.ask("turn 1")
    await agent.ask("turn 2")
    await agent.ask("turn 3")  # age 3, would normally compress

    tool_msg = next(m for m in agent.history if m.get("role") == "tool")
    assert "padding line" in tool_msg["content"]
    assert "[compressed:" not in tool_msg["content"]

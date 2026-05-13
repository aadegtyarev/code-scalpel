"""Headless agent runtime — the channel every entry point shares.

The TUI builds one on startup; probe / bench / spy build their own with
the same config and run turns through it. Anything that's not pure
rendering belongs here so the two stay in lockstep — when a user
reports a behaviour in the TUI, reproducing it from the probe is
literally `await runtime.stream(text).__anext__()`.

Lesson behind the class (2026-05-12): the TUI was appending
"(Reply in X.)" via `Session.prepare_turn` and the probe wasn't.
Same model, same seed, two different agents — qwen flipped between
"explain-in-the-abstract" mode and tool-using mode just from that
suffix. Channel divergence is the first suspect when probe and TUI
disagree, so we collapse the channels into one class with one
entry point.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from code_scalpel.agent import StepAgent, StepResult, StreamItem
from code_scalpel.config import AppConfig
from code_scalpel.llm.adapter import LLMAdapter, OpenAICompatibleAdapter
from code_scalpel.memory import MemoryStore
from code_scalpel.session import Session
from code_scalpel.tools.agent_tools import ConfirmShellExec


class Runtime:
    """Owns the per-session quartet (session, llm, memory, agent) and the
    one method everyone should call to run a turn.

    Construct with `cwd` + `config`. Pass `llm=...` to inject a custom
    adapter (spy, mock). Pass `with_memory=False` to skip the sqlite-
    backed MemoryStore — useful for tests that don't want a file written
    under cwd.
    """

    def __init__(
        self,
        *,
        cwd: Path,
        config: AppConfig,
        llm: LLMAdapter | None = None,
        with_memory: bool = True,
        confirm_shell_exec: ConfirmShellExec | None = None,
    ) -> None:
        self.cwd = cwd
        self.config = config
        self.session = Session()
        if llm is None:
            profile = config.current_profile
            llm = OpenAICompatibleAdapter(
                base_url=f"{profile.provider_base_url()}/v1",
                api_key=profile.api_key(),
                model=profile.model,
                timeout=float(config.agent.llm_timeout),
                cost_per_1k=profile.cost_per_1k,
            )
        self.llm = llm
        self.memory: MemoryStore | None = MemoryStore(root=cwd) if with_memory else None
        self.agent = StepAgent(
            llm=self.llm,
            cwd=cwd,
            config=config,
            memory=self.memory,
            confirm_shell_exec=confirm_shell_exec,
            session=self.session,
        )

    async def stream(
        self,
        raw_text: str,
        *,
        mode: str = "ask",
    ) -> AsyncIterator[StreamItem]:
        """Run one turn through the canonical pipeline:
        Session.prepare_turn → StepAgent.stream_ask. Every user-input
        path goes through here — TUI, probe, spy, bench."""
        task = self.session.prepare_turn(raw_text)
        async for item in self.agent.stream_ask(task, mode=mode):
            yield item

    async def ask(self, raw_text: str, *, mode: str = "ask") -> StepResult:
        """Non-streaming wrapper — same pipeline, collected into a
        StepResult. Mirrors `StepAgent.ask` but keeps prepare_turn in
        the loop."""
        task = self.session.prepare_turn(raw_text)
        return await self.agent.ask(task, mode=mode)

    async def code_with_retry(self, raw_text: str, *, mode: str = "code") -> StepResult:
        """Iterative patch loop — same prepare_turn front-door."""
        task = self.session.prepare_turn(raw_text)
        return await self.agent.code_with_retry(task, mode=mode)

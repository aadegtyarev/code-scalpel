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
from code_scalpel.fork import (
    ChoiceUIHook,
    ForkOption,
    ForkResolution,
    HumanForker,
    UpstreamForker,
    UpstreamProfile,
)
from code_scalpel.llm.adapter import LLMAdapter, OpenAICompatibleAdapter
from code_scalpel.memory import MemoryStore
from code_scalpel.session import Session
from code_scalpel.tools.agent_tools import ConfirmShellExec
from code_scalpel.upstream_queue import (
    FlushOutcome,
    FlushSummary,
    UpstreamPendingQueue,
)


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
        fork_ui_hook: ChoiceUIHook | None = None,
        upstream_profile: UpstreamProfile | None = None,
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
        # Upstream batching state. When `upstream_profile` is set,
        # HumanForker queues forks here instead of resolving them
        # straight away; run_plan / explicit /escalate flush the
        # queue through the upstream model in one batch (cheaper
        # for paid APIs, cheaper for GPU swap on a single host).
        self.upstream_profile = upstream_profile
        self.upstream_queue = UpstreamPendingQueue() if upstream_profile else None
        self.agent = StepAgent(
            llm=self.llm,
            cwd=cwd,
            config=config,
            memory=self.memory,
            confirm_shell_exec=confirm_shell_exec,
            session=self.session,
            upstream_queue=self.upstream_queue,
        )
        # Fork resolver. TUI passes a ui_hook that mounts a ChoiceCard
        # and awaits the user; headless callers (probe / bench) leave
        # it None and HumanForker falls through per
        # config.agent.fork_human_fallback. The forker is reusable —
        # one per Runtime, picks up the latest trust level via config
        # on each call.
        self.fork_resolver = HumanForker(
            self.agent,
            ui_hook=fork_ui_hook,
            config=config.agent,
            upstream_queue=self.upstream_queue,
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

    async def fork(
        self,
        question: str,
        options: tuple[ForkOption, ...],
        context: str,
        *,
        critical: bool = False,
    ) -> ForkResolution:
        """Delegate an architectural choice through the configured
        resolver. Trust (Ctrl+L) drives whether the human picks, the
        model picks (LocalMeta), or it depends on `critical`. Call
        sites in /plan and /go land in v0.11 «fork wiring»; this
        method is the public seam they'll reach for.
        """
        return await self.fork_resolver.resolve(question, options, context, critical=critical)

    async def flush_upstream(self) -> FlushSummary:
        """Drain the pending upstream queue, run each entry through
        UpstreamForker, aggregate the results.

        Override decisions don't auto-rewrite code. They're
        recorded with the commit SHAs that ran during the queue's
        lifetime, so the user can review through `/review-overrides`
        and decide. No-op when `upstream_profile` is unset or the
        queue is empty — callers (run_plan, /escalate) can invoke
        this unconditionally at the end of their flow.
        """
        if self.upstream_queue is None or self.upstream_profile is None:
            return FlushSummary(confirms=0, overrides=())
        if self.upstream_queue.is_empty():
            return FlushSummary(confirms=0, overrides=())

        forker = UpstreamForker(self.upstream_profile)
        confirms = 0
        overrides: list[FlushOutcome] = []
        errors: list[str] = []
        for fork, commits in self.upstream_queue.drain():
            try:
                upstream_resolution = await forker.resolve(
                    fork.question, fork.options, fork.context
                )
            except Exception as e:
                errors.append(f"{fork.fingerprint}: {e}")
                continue
            overridden = upstream_resolution.chosen != fork.picker_resolution.chosen
            outcome = FlushOutcome(
                fork=fork,
                upstream_resolution=upstream_resolution,
                overridden=overridden,
                commits_touched=tuple(commits),
            )
            if overridden:
                overrides.append(outcome)
            else:
                confirms += 1
        return FlushSummary(
            confirms=confirms,
            overrides=tuple(overrides),
            errors=tuple(errors),
        )

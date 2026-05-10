from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from code_scalpel.config import AppConfig
from code_scalpel.llm.adapter import ChatResponse, LLMAdapter
from code_scalpel.patch.parser import extract_patch
from code_scalpel.tools.files import list_files, read_file

_SYSTEM_PROMPT = """\
You are a coding assistant.

When the task requires modifying files, output a unified diff in a ```diff block.
Use standard git diff format: --- a/file and +++ b/file headers, @@ hunks.

For questions or conversation that require no file changes, respond with plain text — no diff."""


@dataclass(frozen=True)
class StepResult:
    reply: str
    patch: str | None
    response: ChatResponse


class StepAgent:
    """Minimal single-step agent: build context → call LLM → extract patch."""

    def __init__(self, llm: LLMAdapter, cwd: Path, config: AppConfig) -> None:
        self._llm = llm
        self._cwd = cwd
        self._config = config

    async def ask(self, task: str) -> StepResult:
        messages = self._build_messages(task)
        profile = self._config.current_profile
        response = await self._llm.chat(messages, **profile.inference_kwargs())
        patch = extract_patch(response.content)
        return StepResult(reply=response.content, patch=patch, response=response)

    async def stream_ask(self, task: str) -> AsyncIterator[str]:
        """Yield content chunks as the model generates them."""
        messages = self._build_messages(task)
        profile = self._config.current_profile
        async for chunk in self._llm.stream(messages, **profile.inference_kwargs()):
            yield chunk

    def _build_messages(self, task: str) -> list[dict[str, str]]:
        context = self._build_context()
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"{context}\n\nTask: {task}"},
        ]

    def _build_context(self) -> str:
        cfg = self._config.agent
        files = list_files(self._cwd, max_files=cfg.max_files)
        parts: list[str] = [f"Files in project ({len(files)} shown):"]
        for rel in files:
            content = read_file(self._cwd / rel, max_lines=cfg.max_file_lines)
            parts.append(f"\n### {rel}\n{content}")
        return "\n".join(parts)

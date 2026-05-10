from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from code_scalpel.config import AppConfig
from code_scalpel.llm.adapter import ChatResponse, LLMAdapter
from code_scalpel.patch.edit_block import Edit, extract_edits
from code_scalpel.tools.files import list_files, read_file

_SYSTEM_PROMPT = """\
You are code-scalpel, a local coding assistant powered by an open-source model.
You are NOT Claude, ChatGPT, or any commercial AI assistant. Never claim to be made
by Anthropic, OpenAI, or any other vendor.

Always reply in the same natural language the user used in their last message.

For questions or conversation that require no file changes, respond with plain text only.

To modify a file, output one or more SEARCH/REPLACE blocks. Format:

    path/to/file.py
    ```python
    <<<<<<< SEARCH
    <lines that currently exist in the file, EXACTLY>
    =======
    <lines that should replace them>
    >>>>>>> REPLACE
    ```

Rules:
- The SEARCH block must match the file content character-for-character.
- To create a new file, leave SEARCH empty.
- Make multiple smaller blocks rather than one big block.
- Keep replies short. Only return blocks (or plain text for questions)."""

_FEW_SHOT_USER = """\
Files in project (1 total):
- mathutil.py

### mathutil.py
1  def add(a, b):
2      return a + b

Task: add type hints — int parameters, int return."""

_FEW_SHOT_ASSISTANT = """\
mathutil.py
```python
<<<<<<< SEARCH
def add(a, b):
    return a + b
=======
def add(a: int, b: int) -> int:
    return a + b
>>>>>>> REPLACE
```"""


@dataclass(frozen=True)
class StepResult:
    reply: str
    edits: list[Edit]
    response: ChatResponse

    @property
    def patch(self) -> list[Edit] | None:
        """Back-compat alias used by some tests / the TUI flow."""
        return self.edits if self.edits else None


class StepAgent:
    """Minimal single-step agent: build context → call LLM → extract edits."""

    def __init__(self, llm: LLMAdapter, cwd: Path, config: AppConfig) -> None:
        self._llm = llm
        self._cwd = cwd
        self._config = config

    async def ask(self, task: str) -> StepResult:
        messages = self._build_messages(task)
        profile = self._config.current_profile
        response = await self._llm.chat(messages, **profile.inference_kwargs())
        edits = extract_edits(response.content)
        return StepResult(reply=response.content, edits=edits, response=response)

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
            {"role": "user", "content": _FEW_SHOT_USER},
            {"role": "assistant", "content": _FEW_SHOT_ASSISTANT},
            {"role": "user", "content": f"{context}\n\nTask: {task}"},
        ]

    def _build_context(self) -> str:
        cfg = self._config.agent
        all_files = list_files(self._cwd, max_files=200)
        listing = "\n".join(f"- {rel}" for rel in all_files)
        parts: list[str] = [
            f"Files in project ({len(all_files)} total):",
            listing,
        ]
        for rel in all_files[: cfg.max_files]:
            content = read_file(self._cwd / rel, max_lines=cfg.max_file_lines)
            parts.append(f"\n### {rel}\n{content}")
        return "\n".join(parts)

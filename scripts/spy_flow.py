"""Spy on a single agent turn — dump every payload and every response.

Used to understand WHY a probe answer looks wrong. We see what the
model actually receives and what it actually emits — system prompt,
user message, tool calls (if any), tool results, raw response text.

Run: `source .venv/bin/activate && python scripts/spy_flow.py [question]`

With no argument, runs the original `flow` regression question.
Quote multi-word questions or it'll only spy on the first token.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from code_scalpel.agent import ToolExecuted
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.llm.adapter import (
    LLMAdapter,
    NativeToolCall,
    OpenAICompatibleAdapter,
    StreamChunk,
)
from code_scalpel.runtime import Runtime

_DEFAULT_QUESTION = (
    "Как идёт обработка от ввода пользователя до вызова LLM? Назови ключевые модули по порядку."
)
QUESTION = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_QUESTION

_CONFIG = AppConfig(
    profiles={
        "local": ModelProfile(
            provider="lmstudio",
            model="qwen/qwen2.5-coder-14b",
            seed=42,
        )
    },
    agent=AgentConfig(max_files=200, max_file_lines=400),
)


def _fmt_messages(messages: list[dict[str, Any]]) -> str:
    """Short-form view of the message list sent to the model."""
    rows = []
    for i, m in enumerate(messages):
        role = m.get("role", "?")
        content = m.get("content")
        if content is None:
            content_view = "<none>"
        else:
            text = str(content)
            content_view = text if len(text) < 400 else text[:400] + f"… (+{len(text) - 400} chars)"
        tc = m.get("tool_calls")
        tc_view = ""
        if tc:
            tc_view = "  tool_calls=" + ", ".join(
                f"{c['function']['name']}({c['function']['arguments'][:60]})" for c in tc
            )
        tcid = m.get("tool_call_id", "")
        tcid_view = f"  [tool_call_id={tcid}]" if tcid else ""
        rows.append(f"  [{i}] role={role}{tcid_view}\n      content: {content_view}{tc_view}")
    return "\n".join(rows)


class SpyAdapter:
    """Wraps a real adapter, logs every stream() call."""

    def __init__(self, inner: LLMAdapter) -> None:
        self._inner = inner
        self.calls: list[dict[str, Any]] = []

    def set_model(self, model: str) -> None:
        self._inner.set_model(model)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **kw: Any,
    ) -> Any:
        return await self._inner.chat(messages, tools=tools, **kw)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        **kw: Any,
    ) -> AsyncIterator[StreamChunk]:
        call_no = len(self.calls) + 1
        print(f"\n{'=' * 76}")
        print(f"LLM CALL #{call_no} — messages going in:")
        print("=" * 76)
        print(_fmt_messages(messages))
        print(f"\n  tools offered: {[t['function']['name'] for t in (tools or [])]}")
        print(f"  inference kwargs: {kw}")

        text_acc = ""
        tool_calls: list[NativeToolCall] = []
        async for chunk in self._inner.stream(messages, tools=tools, **kw):
            if chunk.text:
                text_acc += chunk.text
            if chunk.tool_call is not None:
                tool_calls.append(chunk.tool_call)
            yield chunk

        print(f"\n--- LLM RESPONSE #{call_no} ---")
        if text_acc:
            view = (
                text_acc
                if len(text_acc) < 800
                else text_acc[:800] + f"… (+{len(text_acc) - 800} chars)"
            )
            print(f"text:\n{view}")
        else:
            print("text: <empty>")
        if tool_calls:
            print(f"tool_calls ({len(tool_calls)}):")
            for tc in tool_calls:
                print(f"  - {tc.name}({tc.arguments})")
        else:
            print("tool_calls: <none>")

        self.calls.append({"messages": messages, "text": text_acc, "tool_calls": tool_calls})


async def main() -> None:
    real = OpenAICompatibleAdapter(
        base_url="http://localhost:1234/v1",
        api_key="lm-studio",
        model="qwen/qwen2.5-coder-14b",
    )
    spy = SpyAdapter(real)
    # Inject the SpyAdapter into Runtime — same construction the TUI /
    # probe use, so what the spy sees is what the user sees.
    runtime = Runtime(cwd=Path("."), config=_CONFIG, llm=spy, with_memory=False)

    print(f"\nRaw question: {QUESTION}")
    print("Running runtime.stream…")

    tool_events: list[tuple[str, str, str]] = []
    async for item in runtime.stream(QUESTION):
        if isinstance(item, ToolExecuted):
            tool_events.append((item.call.name, item.call.body, item.result.output[:200]))

    print(f"\n{'=' * 76}")
    print(f"SUMMARY: {len(spy.calls)} LLM call(s), {len(tool_events)} tool executions")
    print("=" * 76)
    for i, (name, args, out) in enumerate(tool_events, 1):
        print(f"  [{i}] {name}({args}) → {out[:120]!r}")
    if not tool_events:
        print("  ⚠  Model did NOT call any tools — answered straight from training.")

    print(f"\n{'=' * 76}")
    print("FINAL ASSISTANT TEXT (last LLM call):")
    print("=" * 76)
    if spy.calls:
        print(spy.calls[-1]["text"])

    # Dump full transcript to /tmp for offline inspection.
    out_path = Path("/tmp/spy_flow.json")
    out_path.write_text(
        json.dumps(
            [
                {
                    "messages": call["messages"],
                    "text": call["text"],
                    "tool_calls": [
                        {"name": tc.name, "arguments": tc.arguments} for tc in call["tool_calls"]
                    ],
                }
                for call in spy.calls
            ],
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\nFull transcript dumped to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())

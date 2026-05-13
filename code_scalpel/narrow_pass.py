"""Narrow LLM passes — single-purpose turns with custom prompts and
sampling settings.

v0.8 reliability bet: a 14b builder loop on its own is fragile, but
combining it with independent reviewer / sanity / commit-msg turns —
each cheap, each scoped, each with a different system prompt — gets
us materially closer to GPT-4-level discipline without the cost.
Annotation pass (v0.7) was the first example of this pattern; this
module makes it first-class so test_sanity / per_step_review /
commit_msg can ride the same rails.

The pass itself is data: name, system_prompt, temperature. Execution
is one short helper on the agent that builds the messages, calls the
LLM, hands the response to a parser (if any). No tool loop, no
history threading — narrow passes are stateless by design. That's
the whole point: every fresh turn carries only its own ask.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NarrowPass:
    """One independent LLM turn with a fixed system prompt and
    sampling profile.

    `name` shows up in logs and synthetic tool cards. `system_prompt`
    is the role-defining message — keep it tight, weak models drift
    when given a paragraph of vague guidance. `temperature` overrides
    the per-mode default; reviewers tend to want it higher, sanity
    checks lower.

    `output_schema` — optional JSON Schema for sampler-enforced
    structured output (LM Studio / OpenAI / OpenRouter all support
    `response_format=json_schema`). When set, the model is guaranteed
    to emit valid JSON conforming to the schema, no prompt-begging.
    Probe (scripts/probe_forks.py) showed structured output on 14b
    is faster than JSON-via-prompt and equally token-efficient.
    """

    name: str
    system_prompt: str
    temperature: float = 0.0
    output_schema: dict[str, Any] | None = field(default=None)


@dataclass(frozen=True)
class PassResult:
    """Output of one narrow pass — raw assistant text plus the token
    counts so callers can decide whether the run was worth it.

    Structured parsing is left to the caller (per-step review wants a
    risk list, test_sanity wants verdict+reason, commit_msg wants a
    one-liner). The pass itself returns the bytes.
    """

    name: str
    text: str
    prompt_tokens: int
    completion_tokens: int

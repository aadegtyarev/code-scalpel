"""Fork delegation — v0.10's reliability bet.

On an architectural question the 14b builder isn't a good judge.
This module abstracts "ask someone smarter than this turn to pick"
into one function: `fork(question, options, context, resolver)`.

The resolver decides who gets to answer:

- `HumanForker` — render a ChoiceCard, wait for the user. Default
  for interactive sessions.
- `LocalMetaForker` — same local model, different system prompt
  ("you are an architect, pick one option, explain in 3 lines, no
  code"), temperature 0.0. Cheap; lets /go keep moving when the
  user isn't watching.
- `UpstreamForker` — a separately-configured stronger model.
  Reserved for genuinely expensive decisions; not part of the
  first cut.

The same machinery handles resume («restart vs continue») and
`code-scalpel init` (provider / model / sandbox choices) — those are
just forks with a fixed set of options and a `human` resolver.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_scalpel import prompts as _prompts
from code_scalpel.narrow_pass import NarrowPass

if TYPE_CHECKING:
    from code_scalpel.agent import StepAgent


@dataclass(frozen=True)
class ForkOption:
    """One choice in a fork.

    `name` is the identifier the resolver returns; `summary` is the
    one-line human-readable description shown next to it. Both are
    fed to the LLM verbatim in local_meta mode — keep them tight.
    """

    name: str
    summary: str


@dataclass(frozen=True)
class ForkResolution:
    """Output of a fork.

    `chosen` is one of the input option names (resolvers MUST return
    a valid name; the API enforces this). `reasoning` is the
    short why-string the user / log sees; LocalMetaForker fills it
    from the model's reply, HumanForker from a textbox or empty.
    """

    chosen: str
    reasoning: str


class ForkError(RuntimeError):
    """Raised when no resolver can decide — e.g. local_meta returns
    invalid JSON twice in a row, or the human cancelled the dialog.

    Callers catch and either bubble up, fall through to a safe
    default, or escalate to a human if the resolver was automated.
    """


# Human resolvers are TUI-side and signature-only here. The TUI
# implements `async (question, options, context) -> ForkResolution`
# using ChoiceCard; we hold the contract as a Callable so /go can be
# tested without a UI.
HumanResolver = Callable[[str, tuple[ForkOption, ...], str], Awaitable[ForkResolution]]


class LocalMetaForker:
    """Resolver that re-uses the local LLM with an architect system
    prompt and strict JSON output. Cheap, deterministic per-seed,
    works without user input — the default «keep /go moving»
    fallback when human isn't available."""

    def __init__(self, agent: StepAgent) -> None:
        self._agent = agent

    async def resolve(
        self,
        question: str,
        options: tuple[ForkOption, ...],
        context: str,
    ) -> ForkResolution:
        if not options:
            raise ForkError("no options to choose from")
        options_block = "\n".join(f"- {o.name}: {o.summary}" for o in options)
        user_message = (
            f"Question:\n{question}\n\nOptions:\n{options_block}\n\nContext:\n{context}\n"
        )
        pass_spec = NarrowPass(
            name="fork_local_meta",
            system_prompt=_prompts.FORK_LOCAL_META,
            # 0.0 — picking an option is a judgement, not a creative
            # writing task. The user wants reproducible /go runs.
            temperature=0.0,
        )
        result = await self._agent.run_narrow_pass(pass_spec, user_message)
        return _parse_resolver_reply(result.text, options)


def _parse_resolver_reply(text: str, options: tuple[ForkOption, ...]) -> ForkResolution:
    """Tolerant JSON parse — model sometimes wraps in ```json … ```
    or leaks a stray sentence before the brace. We extract the first
    `{ … }` block and validate `chosen` against the option set."""
    payload = _extract_json_object(text)
    if payload is None:
        raise ForkError(f"resolver returned non-JSON: {text[:200]!r}")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ForkError(f"resolver returned invalid JSON: {e}") from e
    chosen = str(data.get("chosen", "")).strip()
    reasoning = str(data.get("reasoning", "")).strip()
    valid = {o.name for o in options}
    if chosen not in valid:
        raise ForkError(f"resolver chose {chosen!r}, not in options ({', '.join(sorted(valid))})")
    return ForkResolution(chosen=chosen, reasoning=reasoning)


def _extract_json_object(text: str) -> str | None:
    """Find the first balanced { … } in `text`.

    Why not `json.loads(text)` directly: weak models prepend
    "Here is my answer:" or wrap in a fenced block. The brace
    tracker is a defensive parse — counts open/close braces ignoring
    those inside strings — and returns the first balanced span.
    """
    in_string = False
    escape = False
    start = -1
    depth = 0
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start : i + 1]
    return None


__all__ = [
    "ForkError",
    "ForkOption",
    "ForkResolution",
    "HumanResolver",
    "LocalMetaForker",
]

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
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_scalpel import prompts as _prompts
from code_scalpel.narrow_pass import NarrowPass

if TYPE_CHECKING:
    from code_scalpel.agent import StepAgent
    from code_scalpel.config import AgentConfig


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


# Outcome of one ChoiceCard render. A real key means the user
# picked (or pressed `?` to clarify, or `*` to delegate to Auto);
# `None` means the timeout fired without an answer; "esc" means
# the user cancelled. The TUI hook returns one of these; fork.py
# owns the interpretation.
ChoiceOutcome = str | None

# UI hook: render a ChoiceCard for these options with this title
# and timeout; await one of the outcomes above. `None` for
# timeout_s means «no timeout». Keys reserved by HumanForker:
#   '?'  — clarify (expand option summaries)
#   '*'  — let the model pick (LocalMeta delegation)
#   'esc' — cancel (raises ForkError)
ChoiceUIHook = Callable[
    [str, tuple["ChoiceCardOption", ...], int | None],
    Awaitable[ChoiceOutcome],
]


@dataclass(frozen=True)
class ChoiceCardOption:
    """Minimal contract for the UI hook. The TUI maps this onto its
    own ChoiceCard widget; tests use a fake hook that ignores the
    rendering and returns a hard-coded outcome."""

    key: str
    label: str
    description: str = ""


# Legacy alias — old call sites referenced this name.
HumanResolver = Callable[[str, tuple[ForkOption, ...], str], Awaitable[ForkResolution]]


_RESOLVER_SCHEMA = {
    "type": "object",
    "properties": {
        "chosen": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["chosen", "reasoning"],
    "additionalProperties": False,
}


_AUTO_KEY = "*"  # «let the model pick» — delegate to LocalMetaForker
_CLARIFY_KEY = "?"  # «explain» — run the clarify pass and redraw
_LETTER_BUCKET = "abcdefgh"  # up to 8 options; more → ForkError


def _bucket_options(options: tuple[ForkOption, ...]) -> tuple[ChoiceCardOption, ...]:
    """Map ForkOption (name+summary, no UI key) onto ChoiceCardOption
    (key+label+description). The key is a letter from `a` upward; the
    name lives in the label so the user reads the actual choice.

    Reserves `?` for clarify and `*` for «let the model pick». The
    cap at 8 letters is intentional — a list of 12 options is itself
    a smell that the model needs to narrow before asking.
    """
    if len(options) > len(_LETTER_BUCKET):
        raise ForkError(f"too many options ({len(options)}); fork should narrow to ≤8 first")
    out: list[ChoiceCardOption] = []
    for i, opt in enumerate(options):
        out.append(
            ChoiceCardOption(
                key=_LETTER_BUCKET[i],
                label=opt.name,
                description=opt.summary,
            )
        )
    out.append(ChoiceCardOption(key=_CLARIFY_KEY, label="explain", description="expand options"))
    out.append(ChoiceCardOption(key=_AUTO_KEY, label="auto", description="let the model pick"))
    return tuple(out)


def _timeout_for_trust(trust: str, critical: bool, cfg: AgentConfig) -> int | None:
    """Map trust × critical onto a ChoiceCard timeout in seconds.

    skeptic — None (no timeout, user must answer).
    optimist — fork_human_timeout_optimist; timeout falls through to Auto.
    yolo + critical — fork_human_timeout_yolo_critical; timeout → Auto.
    yolo + non-critical — caller should not render a ChoiceCard at all
    (HumanForker.resolve handles that branch by going straight to
    LocalMetaForker; this helper isn't called).
    """
    if trust == "skeptic":
        return None
    if trust == "optimist":
        return cfg.fork_human_timeout_optimist
    if trust == "yolo" and critical:
        return cfg.fork_human_timeout_yolo_critical
    # yolo + non-critical never reaches this code path.
    return None


class HumanForker:
    """Interactive resolver. Renders a ChoiceCard, awaits the user.

    Behaviour follows `trust` (Ctrl+L), same axis that already
    governs shell_exec / patch-apply — one mental model, fewer
    knobs:

      skeptic   — card with no timeout, user picks or `?`-expands.
      optimist  — card with a countdown; timeout → LocalMetaForker.
      yolo      — straight to LocalMetaForker, EXCEPT `critical=True`
                  forks (those still render a short countdown card).

    `ui_hook` is the bridge to the TUI. Tests pass a fake hook that
    returns hard-coded outcomes; the real TUI mounts a ChoiceCard
    widget and resolves via its `ChoiceDecision` message.

    Headless callers (no `ui_hook`) fall through according to
    `AgentConfig.fork_human_fallback` — `local_meta` keeps the run
    moving, `error` halts.
    """

    def __init__(
        self,
        agent: StepAgent,
        *,
        ui_hook: ChoiceUIHook | None,
        config: AgentConfig,
    ) -> None:
        self._agent = agent
        self._ui_hook = ui_hook
        self._config = config

    async def resolve(
        self,
        question: str,
        options: tuple[ForkOption, ...],
        context: str,
        *,
        critical: bool = False,
    ) -> ForkResolution:
        if not options:
            raise ForkError("no options to choose from")

        trust = self._config.trust

        # yolo + non-critical: model picks straight away. Critical
        # forks fall through to the ChoiceCard branch so the user
        # always has a brief window to intercept the things they
        # specifically said are important.
        if trust == "yolo" and not critical:
            return await self._delegate_to_local_meta(question, options, context)

        # No UI → headless policy. Both `skeptic` and `optimist` need
        # a card; without one we either fall back or halt.
        if self._ui_hook is None:
            return await self._handle_headless(question, options, context)

        timeout = _timeout_for_trust(trust, critical, self._config)

        # Clarify loop: each `?` press triggers an expand-pass and
        # re-renders the card with richer descriptions. Bounded only
        # by the user's patience — no cap (S1 from the design
        # conversation: bounded loops felt arbitrary, user lives
        # and decides when enough is enough).
        current_options = options
        clarify_round = 0
        while True:
            card_options = _bucket_options(current_options)
            outcome = await self._ui_hook(question, card_options, timeout)
            if outcome is None:
                # Timeout. Skeptic never times out (timeout was
                # None); optimist / yolo+critical fall through to
                # Auto. Same as if the user pressed `*` manually.
                return await self._delegate_to_local_meta(question, options, context)
            if outcome == "esc":
                raise ForkError("user cancelled the fork")
            if outcome == _AUTO_KEY:
                return await self._delegate_to_local_meta(question, options, context)
            if outcome == _CLARIFY_KEY:
                clarify_round += 1
                current_options = await self._clarify(
                    question, current_options, context, clarify_round
                )
                continue
            # Letter key → look up the original option by index.
            try:
                idx = _LETTER_BUCKET.index(outcome)
            except ValueError as e:
                raise ForkError(f"unknown outcome: {outcome!r}") from e
            if idx >= len(options):
                raise ForkError(f"outcome {outcome!r} past option list")
            return ForkResolution(chosen=options[idx].name, reasoning="")

    async def _delegate_to_local_meta(
        self,
        question: str,
        options: tuple[ForkOption, ...],
        context: str,
    ) -> ForkResolution:
        """Auto-pipeline entry. Default = ReviewedAuto (v0.11 bet);
        opt-out via `fork_auto_reviewed=False` for callers that
        prefer the single-pass LocalMeta path (faster, no reviewer
        safety net)."""
        if self._config.fork_auto_reviewed:
            return await ReviewedAutoForker(self._agent).resolve(question, options, context)
        return await LocalMetaForker(self._agent).resolve(question, options, context)

    async def _handle_headless(
        self,
        question: str,
        options: tuple[ForkOption, ...],
        context: str,
    ) -> ForkResolution:
        """No UI hook → consult `fork_human_fallback`.

        We print to stderr so a silent fall-through never hides the
        fact a human fork was about to fire. Probe / bench owners
        need to see this in their logs.
        """
        policy = self._config.fork_human_fallback
        if policy == "error":
            raise ForkError(
                "human fork requested but no UI hook is registered "
                "(set fork_human_fallback='local_meta' to auto-pick)"
            )
        print(
            f"[fork] no UI hook; falling back to local_meta for question: {question[:60]}",
            file=sys.stderr,
        )
        return await self._delegate_to_local_meta(question, options, context)

    async def _clarify(
        self,
        question: str,
        options: tuple[ForkOption, ...],
        context: str,
        round_no: int,
    ) -> tuple[ForkOption, ...]:
        """Run an expand pass — same option set, richer descriptions.

        We re-use the existing options' names (the user is comparing
        the same choices) and overwrite `summary` with the model's
        expanded line for that option. If the model's reply doesn't
        parse cleanly, fall back to the original summaries so the
        user isn't stranded with empty descriptions.
        """
        options_block = "\n".join(f"- {o.name}: {o.summary}" for o in options)
        user_message = (
            f"Question:\n{question}\n\n"
            f"Options:\n{options_block}\n\n"
            f"Context:\n{context}\n\n"
            f"This is clarify round {round_no}. "
            "Push deeper than the previous round; surface concrete "
            "gotchas the user can't infer from the option names."
        )
        pass_spec = NarrowPass(
            name="fork_clarify",
            system_prompt=_prompts.FORK_CLARIFY,
            temperature=0.3,
        )
        try:
            result = await self._agent.run_narrow_pass(pass_spec, user_message)
        except Exception:
            return options  # fall back; user still has the original summaries
        new_summaries = _parse_clarify_reply(result.text, options)
        if new_summaries is None:
            return options
        return tuple(
            ForkOption(name=o.name, summary=new_summaries.get(o.name, o.summary)) for o in options
        )


def _parse_clarify_reply(text: str, options: tuple[ForkOption, ...]) -> dict[str, str] | None:
    """Pull per-option expanded summaries out of the clarify pass's
    markdown reply. Looks for `**<name>**` headings; collects the
    text up to the next heading.

    Returns `{name: expanded_summary}` or None if nothing matched
    cleanly (caller falls back to original options)."""
    if not text.strip():
        return None
    name_set = {o.name for o in options}
    chunks: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        match_name = _heading_name(stripped, name_set)
        if match_name is not None:
            current = match_name
            chunks.setdefault(current, [])
            continue
        if current is not None and stripped:
            chunks[current].append(stripped)
    if not chunks:
        return None
    return {name: " ".join(lines).strip() for name, lines in chunks.items() if lines}


def _heading_name(line: str, name_set: set[str]) -> str | None:
    """If `line` is a markdown heading or bold line that names an
    option (`**asyncpg**`, `### asyncpg`, `- **asyncpg**`), return
    the option name. Otherwise None."""
    # Strip markdown decorations to compare against the literal name.
    candidate = line.removeprefix("- ").removeprefix("* ").strip()
    candidate = candidate.removeprefix("#").lstrip("# ").strip()
    candidate = candidate.strip("*_ `:").strip()
    if candidate in name_set:
        return candidate
    return None


class LocalMetaForker:
    """Resolver that re-uses the local LLM with an architect system
    prompt and sampler-enforced JSON output. Cheap, deterministic per
    seed, works without user input — the default «keep /go moving»
    fallback when human isn't available.

    Output discipline comes from `response_format=json_schema`
    (LM Studio / OpenAI / OpenRouter all support it), not from
    prompt-begging. Probe (scripts/probe_forks.py) calibrated this
    on 14b: structured is faster and removes the parser-error class
    entirely vs JSON-via-prompt.

    Fallback path for providers without structured output is the
    same brace-tracking JSON parser — works on free-text JSON too,
    so this code path is forgiving in either world.
    """

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
            output_schema=_RESOLVER_SCHEMA,
        )
        result = await self._agent.run_narrow_pass(pass_spec, user_message)
        return _parse_resolver_reply(result.text, options)


_REVIEWER_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["confirm", "override", "discuss"]},
        "alternative": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["verdict", "alternative", "reasoning"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class _ReviewVerdict:
    """Internal record of the reviewer's call. Verdict is a closed
    enum (confirm / override / discuss); alternative is required only
    on override and validated against the option set before we trust
    it."""

    verdict: str
    alternative: str
    reasoning: str


class ReviewedAutoForker:
    """Two-pass resolver: picker + skeptic reviewer + anchor.

    The 14b builder isn't good at solo architectural judgement. Two
    passes through the same model with different roles get
    materially closer to GPT-4-level review at local cost:

    1. **Picker** (LocalMetaForker, t=0.0). Sampler-enforced
       `{chosen, reasoning}`. Stable, deterministic per seed.
    2. **Reviewer** (NarrowPass, t=0.3, separate prompt).
       Sampler-enforced `{verdict, alternative, reasoning}`.
       Three verdicts:
         • `confirm`         → return picker's choice.
         • `override <name>` → return the named alternative.
         • `discuss`         → anchor to picker (stable t=0.0).

    Anti-loop is structural — no recursion, no review-of-review.
    The hard cap `fork_review_max_overrides=1` is built into the
    two-pass shape, not enforced by a counter.

    Probe (scripts/probe_fork_reviewer.py) calibrated the reviewer
    on qwen2.5-coder-14b: 0/3 rubber-stamp on override-cases,
    3/3 alternative-name accuracy. Confidence to ship it as the
    default Auto path.
    """

    def __init__(self, agent: StepAgent) -> None:
        self._agent = agent
        self._picker = LocalMetaForker(agent)

    async def resolve(
        self,
        question: str,
        options: tuple[ForkOption, ...],
        context: str,
    ) -> ForkResolution:
        if not options:
            raise ForkError("no options to choose from")
        # Step 1 — picker. Failure here bubbles; we don't fall back
        # to anything because the reviewer needs a picker output to
        # have an opinion on.
        picker_choice = await self._picker.resolve(question, options, context)
        # Step 2 — reviewer. If reviewer fails (malformed reply,
        # rare on structured output but possible) we anchor to the
        # picker. Reviewer that crashes shouldn't crash the whole
        # fork.
        try:
            verdict = await self._review(question, options, context, picker_choice)
        except ForkError:
            return picker_choice
        if verdict.verdict == "confirm":
            return picker_choice
        if verdict.verdict == "override":
            return ForkResolution(
                chosen=verdict.alternative,
                reasoning=f"reviewer overrode picker: {verdict.reasoning}",
            )
        # discuss → anchor to picker (t=0.0 is the stable answer).
        # The caller (HumanForker on optimist/yolo-critical timeout
        # paths) gets a deterministic outcome; an interactive caller
        # would have routed to the human instead of falling into the
        # auto pipeline.
        return ForkResolution(
            chosen=picker_choice.chosen,
            reasoning=f"reviewer flagged discuss; anchored to picker: {verdict.reasoning}",
        )

    async def _review(
        self,
        question: str,
        options: tuple[ForkOption, ...],
        context: str,
        picker_choice: ForkResolution,
    ) -> _ReviewVerdict:
        options_block = "\n".join(f"- {o.name}: {o.summary}" for o in options)
        user_message = (
            f"Question:\n{question}\n\n"
            f"Options:\n{options_block}\n\n"
            f"Context:\n{context}\n\n"
            f"Picker's choice: {picker_choice.chosen}\n"
            f"Picker's reasoning: {picker_choice.reasoning}\n"
        )
        pass_spec = NarrowPass(
            name="fork_reviewer",
            system_prompt=_prompts.FORK_REVIEWER,
            # 0.3 — probe showed temperature doesn't affect verdicts
            # (5/6 right at every temp), but 0.3 sits between picker's
            # 0.0 and the default 0.5 so picker and reviewer don't
            # collapse onto the same answer when the model is on the
            # fence.
            temperature=0.3,
            output_schema=_REVIEWER_SCHEMA,
        )
        result = await self._agent.run_narrow_pass(pass_spec, user_message)
        payload = _extract_json_object(result.text)
        if payload is None:
            raise ForkError(f"reviewer returned non-JSON: {result.text[:200]!r}")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            raise ForkError(f"reviewer returned invalid JSON: {e}") from e
        verdict = str(data.get("verdict", "")).strip()
        alternative = str(data.get("alternative", "")).strip()
        reasoning = str(data.get("reasoning", "")).strip()
        if verdict not in ("confirm", "override", "discuss"):
            raise ForkError(f"reviewer returned unknown verdict: {verdict!r}")
        if verdict == "override":
            valid = {o.name for o in options}
            if alternative not in valid:
                # Reviewer named an option that doesn't exist. Treat
                # as discuss — the picker's choice is the safer
                # anchor than a hallucinated alternative.
                return _ReviewVerdict(
                    verdict="discuss",
                    alternative="",
                    reasoning=(
                        f"reviewer suggested unknown option {alternative!r}; demoted to discuss"
                    ),
                )
        return _ReviewVerdict(
            verdict=verdict,
            alternative=alternative,
            reasoning=reasoning,
        )


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
    "ChoiceCardOption",
    "ChoiceUIHook",
    "ForkError",
    "ForkOption",
    "ForkResolution",
    "HumanForker",
    "HumanResolver",
    "LocalMetaForker",
    "ReviewedAutoForker",
]

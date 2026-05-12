"""Trust-level policy.

Three named levels — one knob covers shell_exec policy AND the
patch-apply confirmation gate, because both questions reduce to the
same thing: how much do you trust the model to act without your
review on each step.

  • **skeptic** (default) — every shell_exec call AND every patch
    require manual user confirmation in the TUI before running.
    The shell-exec confirmation UI ships in a follow-up PR; until
    then `decide()` refuses shell_exec in skeptic with a clear
    message pointing at the follow-up.
  • **optimist** — shell_exec and patches auto-apply without
    confirmation, EXCEPT for a small hard-block list that refuses
    commands that would genuinely break the host (`rm -rf /`,
    `dd of=/dev/...`, `mkfs`, privilege escalation, pipe-to-shell,
    fork bomb).
  • **yolo** — auto-apply, zero filtering. Intended for sandbox VMs
    / containers where blowing up doesn't matter. Equivalent to
    running the model as your shell.

Hard blocks are pattern-based on the raw command string. Patterns
err toward catching obvious shapes (`sudo` anywhere, `rm -rf` with
any flag order against root/home) rather than parsing argv
exhaustively — false positives are cheap (refuse, log reason),
false negatives can wipe disks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

TrustLevel = Literal["skeptic", "optimist", "yolo"]

TRUST_LEVELS: tuple[TrustLevel, ...] = ("skeptic", "optimist", "yolo")


@dataclass(frozen=True)
class Decision:
    """Result of `decide()` — either allow with no reason, or refuse
    with a short human-readable reason that surfaces to the model as
    the tool error and to the user in the OutputLog."""

    allowed: bool
    reason: str = ""


# (regex, reason) pairs. Anchored with `\b` where the keyword should
# stand alone. Order is irrelevant for correctness — first match wins.
_HARD_BLOCKS: tuple[tuple[re.Pattern[str], str], ...] = (
    # rm with recursive flag targeting an absolute / home / parent path.
    # Catches `rm -rf /`, `rm -rf /usr`, `rm -fr /var/log`, `rm -r ~`,
    # `rm -rf ..` — flag order is lazy. Doesn't catch `rm -rf foo` or
    # `rm -rf .` (current dir) — those are intentionally narrow scope.
    (
        re.compile(r"\brm\s+(?:-[a-zA-Z]*[rRf][a-zA-Z]*\s+)+(?:/|~|\.\.)\S*"),
        "rm -rf on absolute / home / parent path is hard-blocked",
    ),
    # Direct writes to block devices: `dd of=/dev/sda`, `... > /dev/sdb`.
    (
        re.compile(r"(?:\bdd\b[^|]*?\bof=|>\s*)/dev/(?:sd|hd|nvme|mmcblk|disk)"),
        "writes to block devices are hard-blocked",
    ),
    # Filesystem creation: mkfs.*, mkswap.
    (
        re.compile(r"\bmk(?:fs(?:\.\w+)?|swap)\b"),
        "mkfs / mkswap are hard-blocked",
    ),
    # Privilege escalation — an agent that needs root is operating
    # outside its mandate; refuse regardless of trust level (except yolo).
    (
        re.compile(r"\b(?:sudo|su|doas)\b"),
        "privilege escalation (sudo/su/doas) is hard-blocked",
    ),
    # Pipe-to-shell — canonical remote-execution gadget. Refuse any
    # `... | (bash|sh|zsh|fish)` whether through curl, wget, or local.
    (
        re.compile(r"\|\s*(?:bash|sh|zsh|fish)\b"),
        "pipe-to-shell (... | sh) is hard-blocked — fetch and review first",
    ),
    # Classic fork bomb. The function-def + recursion + background-spawn
    # shape is unmistakable; refusing the literal form catches every
    # variant a model might emit.
    (
        re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&"),
        "fork bomb pattern is hard-blocked",
    ),
)


def decide(command: str, level: TrustLevel) -> Decision:
    """Decide whether a shell command may run at the given trust level.

    - `skeptic` — needs manual UI confirmation; until that UI ships,
      refuse with a clear "UI pending" message.
    - `optimist` — refuse only patterns in `_HARD_BLOCKS`.
    - `yolo` — allow unconditionally.

    Unknown levels coerce to `skeptic` for safety; a typo in config
    shouldn't accidentally unlock shell access.
    """
    if level == "yolo":
        return Decision(allowed=True)
    if level == "optimist":
        for pattern, reason in _HARD_BLOCKS:
            if pattern.search(command):
                return Decision(allowed=False, reason=reason)
        return Decision(allowed=True)
    # skeptic, or anything unknown — needs manual confirm. The
    # confirmation UI is in the follow-up PR; for now we refuse so the
    # user gets a visible "next step" rather than a silent autopilot.
    return Decision(
        allowed=False,
        reason=(
            "shell_exec at trust=skeptic requires manual confirmation. "
            "The confirmation UI is in the next PR; until then set "
            "agent.trust to 'optimist' or 'yolo' to use shell_exec."
        ),
    )


def auto_confirm(level: TrustLevel) -> bool:
    """Whether tool calls AND patch applies skip the manual `[a]/[r]/[g]`
    gate. `skeptic` keeps the manual gate; `optimist`/`yolo` autopilot."""
    return level in ("optimist", "yolo")

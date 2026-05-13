"""Trust-level policy.

Three named levels — one knob covers shell_exec policy AND the
patch-apply confirmation gate, because both questions reduce to the
same thing: how much do you trust the model to act without your
review on each step.

  • **skeptic** (default) — every shell_exec call AND every patch
    require manual user confirmation in the TUI before running.
    `decide()` returns `requires_confirm=True` for non-hard-blocked
    commands; the dispatch layer awaits a UI callback (the TUI
    provides one via `ShellExecCard`, headless callers don't and
    skeptic mode refuses there).
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
    """Result of `decide()` — three shapes:

    • `allowed=True, requires_confirm=False` — run immediately.
    • `allowed=True, requires_confirm=True` — needs interactive
      user confirmation before running (skeptic mode for non-
      hard-blocked commands). The dispatch layer asks the UI;
      if no UI handler is registered, the command is refused.
    • `allowed=False` — hard-blocked; reason explains why.
    """

    allowed: bool
    reason: str = ""
    requires_confirm: bool = False


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
    # Project-directory escape — `cd` (or `pushd`) to an absolute path,
    # home, or parent traversal. We can't sandbox at the kernel level
    # (would need bwrap/firejail), but blocking the `cd` form catches
    # most accidental writes outside the workspace. Subprocess cwd is
    # already pinned to the project root; this just prevents the
    # in-shell `cd && do-stuff` workaround.
    (
        re.compile(r"\b(?:cd|pushd)\s+(?:/|~|\.\.)"),
        "cd to absolute / home / parent path is hard-blocked (stay inside the project)",
    ),
    # Redirect-write to an absolute path. Catches `>/etc/foo`,
    # `>>/var/log/x`, `tee /tmp/y`. Same intent as the cd block —
    # writes must stay inside the project dir.
    (
        re.compile(r"(?:>|>>|\btee\s+(?:-a\s+)?)\s*/(?!dev/(?:null|stdout|stderr|tty)\b)"),
        "redirect-write outside the project is hard-blocked",
    ),
    # File-copying tools writing OUT of the project. We allow them
    # reading from absolute paths (e.g. `cp /etc/template.conf .`) but
    # block writes whose destination is an absolute path outside /tmp.
    # /tmp is permitted because pytest/coverage use it for temp output.
    (
        re.compile(r"\b(?:cp|mv|install|rsync)\b[^|;&]*\s/(?!tmp/)"),
        "copy / move OUT of the project (to an absolute path) is hard-blocked",
    ),
)


def decide(command: str, level: TrustLevel) -> Decision:
    """Decide whether a shell command may run at the given trust level.

    - `skeptic` — apply hard blocks; otherwise allow contingent on
      UI confirmation. Caller dispatches `await confirm(command)`;
      if no handler is registered, the command is refused.
    - `optimist` — refuse only patterns in `_HARD_BLOCKS`.
    - `yolo` — allow unconditionally.

    Unknown levels coerce to `skeptic` for safety; a typo in config
    shouldn't accidentally unlock shell access.
    """
    if level == "yolo":
        return Decision(allowed=True)
    # skeptic AND optimist both run the hard-block check. The hard
    # blocks are about commands that would genuinely break the host
    # (rm -rf /, sudo, mkfs, …); user explicitly approving them in
    # skeptic mode is destruction-by-typo, not "informed consent".
    for pattern, reason in _HARD_BLOCKS:
        if pattern.search(command):
            return Decision(allowed=False, reason=reason)
    if level == "optimist":
        return Decision(allowed=True)
    # skeptic, or anything unknown — non-hard-blocked command needs
    # user confirm. The dispatch layer enforces this via callback.
    return Decision(allowed=True, requires_confirm=True)


def auto_confirm(level: TrustLevel) -> bool:
    """Whether tool calls AND patch applies skip the manual `[a]/[r]/[g]`
    gate. `skeptic` keeps the manual gate; `optimist`/`yolo` autopilot."""
    return level in ("optimist", "yolo")

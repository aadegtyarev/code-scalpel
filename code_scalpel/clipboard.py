"""Cross-platform system clipboard helper.

The TUI has two surfaces that need to copy text out: Ctrl+O modal
(`tool_result_modal`) for the last tool output, and Ctrl+Y on a
focused inline tool-card. Both want the same fallback cascade
(wl-copy → xclip → xsel → pbcopy → clip.exe), so the logic lives
here as a shared utility instead of getting duplicated.

Each candidate is fed text via stdin so multi-line / large inputs
work. wl-copy on a Wayland-less box prints to stderr before
exiting non-zero — we DEVNULL its streams so that noise doesn't
leak into the TUI surface.
"""

from __future__ import annotations

import shutil
import subprocess


def copy_to_system_clipboard(text: str) -> str | None:
    """Try cross-platform clipboard binaries in order. Returns the name
    of the tool that worked, or None if nothing's available. The
    caller decides what to do on None — typically fall back to OSC52
    via `app.copy_to_clipboard`, which works in some terminals.
    """
    candidates: list[tuple[str, list[str]]] = [
        ("wl-copy", ["wl-copy"]),
        ("xclip", ["xclip", "-selection", "clipboard"]),
        ("xsel", ["xsel", "--clipboard", "--input"]),
        ("pbcopy", ["pbcopy"]),
        ("clip.exe", ["clip.exe"]),
    ]
    for name, cmd in candidates:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                check=True,
                timeout=2,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return name
        except (subprocess.SubprocessError, OSError):
            continue
    return None

"""bwrap-based shell sandbox for `shell_exec`.

`bwrap` (bubblewrap) is a small SUID-less Linux sandbox shipped on most
distros (`bubblewrap` package on Debian/Ubuntu/Fedora). It lets us run a
command in a namespace where only the directories we explicitly bind
are visible — perfect for confining model-issued shell commands to the
project workspace.

Filesystem layout inside the sandbox:
  • `/usr`, `/lib`, `/lib64`, `/bin`, `/sbin` — read-only bind from host.
    Python, pytest, pip, shell builtins all live here; without these the
    sandbox can't run anything.
  • `/etc` — read-only bind. Needed for resolv.conf (DNS), passwd, etc.
    The sensitive bits live in /home, not /etc.
  • `/dev` — sandboxed `/dev` (only the safe nodes: null, zero, random,
    tty, …). `--dev /dev` is bwrap's built-in for this.
  • `/proc` — sandboxed proc. `--proc /proc`.
  • `/tmp` — fresh tmpfs (writable but starts empty; vanishes after
    the process exits).
  • `/home` — tmpfs (empty). The model can't see ~/.ssh, ~/.aws, …
  • `<project_dir>` — read-write bind. THIS is where commands run.

Network: shared with host (`--share-net`). Local LLMs and pip both need
it; sealing it off would break the loop. Future work: opt-in `--unshare-net`
mode for stricter setups.

Process namespaces: `--unshare-user --unshare-pid --unshare-uts --unshare-ipc`.
Network namespace is intentionally NOT unshared (see above).

`bwrap_available()` checks for the binary at import time, so the runner
can fall back to plain `run_shell` on hosts without bwrap (macOS, BSDs,
Windows-via-WSL). The fallback runs `cwd=project_dir` so commands still
default to the right directory — they're just not confined.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def bwrap_available() -> bool:
    """True iff a bwrap binary is on PATH. Cached lookup via `shutil.which`."""
    return shutil.which("bwrap") is not None


def wrap_command_with_bwrap(command: str, project_dir: Path) -> list[str]:
    """Build a `bwrap … -- /bin/sh -c <command>` argv that confines the
    given shell command to `project_dir`.

    Returns the full argv ready for `subprocess`. The shell-level command
    string is passed through unchanged — pipes, redirects, env vars all
    work inside the sandbox.
    """
    project_dir = project_dir.resolve()
    argv: list[str] = ["bwrap"]
    # Read-only system roots. We only bind directories that actually exist
    # on the host — Debian/Ubuntu have /lib64 as a symlink, Fedora doesn't.
    for ro in ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/etc"):
        if Path(ro).exists():
            argv += ["--ro-bind-try", ro, ro]
    # Standard sandboxed system mounts.
    argv += [
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        # Empty tmpfs for /tmp — pytest/coverage write here.
        "--tmpfs",
        "/tmp",
        # Empty tmpfs for /home — hides ~/.ssh, ~/.aws, browser profiles…
        "--tmpfs",
        "/home",
        # Read-write project bind. Inside the sandbox the path is the
        # same as on the host; commands written against absolute paths
        # still resolve correctly.
        "--bind",
        str(project_dir),
        str(project_dir),
        "--chdir",
        str(project_dir),
        # Namespaces. We keep network shared (`--share-net` is implicit
        # when we don't ask for `--unshare-net`).
        "--unshare-user",
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-ipc",
        # No PID 1, no zombies left behind.
        "--die-with-parent",
        # End of bwrap args; payload follows.
        "/bin/sh",
        "-c",
        command,
    ]
    return argv


__all__ = ["bwrap_available", "wrap_command_with_bwrap"]

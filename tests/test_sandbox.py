"""Tests for the bwrap sandbox wrapping."""

from __future__ import annotations

from pathlib import Path

from code_scalpel.tools.sandbox import bwrap_available, wrap_command_with_bwrap


def test_wrap_command_starts_with_bwrap(tmp_path: Path) -> None:
    argv = wrap_command_with_bwrap("ls -la", tmp_path)
    assert argv[0] == "bwrap"


def test_wrap_command_binds_project_dir_rw(tmp_path: Path) -> None:
    argv = wrap_command_with_bwrap("ls", tmp_path)
    # `--bind <project> <project>` somewhere in the argv. We assert on the
    # PAIR (consecutive) because bwrap requires it that way.
    project_str = str(tmp_path.resolve())
    found = False
    for i in range(len(argv) - 2):
        if argv[i] == "--bind" and argv[i + 1] == project_str and argv[i + 2] == project_str:
            found = True
            break
    assert found, f"--bind {project_str} {project_str} pair missing from {argv}"


def test_wrap_command_chdirs_to_project(tmp_path: Path) -> None:
    argv = wrap_command_with_bwrap("ls", tmp_path)
    project_str = str(tmp_path.resolve())
    # --chdir <project>
    idx = argv.index("--chdir")
    assert argv[idx + 1] == project_str


def test_wrap_command_home_is_tmpfs(tmp_path: Path) -> None:
    """Critical security property: /home must NOT be bound from host."""
    argv = wrap_command_with_bwrap("ls", tmp_path)
    home_indices = [i for i, a in enumerate(argv) if a == "/home"]
    assert home_indices, "no /home mount declared at all"
    # For each /home appearance, the PRECEDING token must be --tmpfs.
    for i in home_indices:
        assert argv[i - 1] == "--tmpfs", (
            f"/home at index {i} preceded by {argv[i - 1]!r}, not --tmpfs"
        )


def test_wrap_command_etc_readonly(tmp_path: Path) -> None:
    """/etc is needed for DNS/resolv.conf but must be read-only."""
    argv = wrap_command_with_bwrap("ls", tmp_path)
    # We use --ro-bind-try /etc /etc (try variant — tolerates missing /etc).
    for i, a in enumerate(argv):
        if a == "/etc" and i > 0 and "bind" in argv[i - 2]:
            assert "ro" in argv[i - 2], f"/etc mount via {argv[i - 2]!r} is NOT read-only"


def test_wrap_command_uses_sh_payload(tmp_path: Path) -> None:
    argv = wrap_command_with_bwrap("echo hi", tmp_path)
    assert argv[-3] == "/bin/sh"
    assert argv[-2] == "-c"
    assert argv[-1] == "echo hi"


def test_wrap_command_unshares_user_pid(tmp_path: Path) -> None:
    """User and PID namespaces unshared (zombie containment + uid mapping)."""
    argv = wrap_command_with_bwrap("ls", tmp_path)
    assert "--unshare-user" in argv
    assert "--unshare-pid" in argv


def test_wrap_command_keeps_network(tmp_path: Path) -> None:
    """We do NOT unshare net — pip and local LLM HTTP both need it."""
    argv = wrap_command_with_bwrap("ls", tmp_path)
    assert "--unshare-net" not in argv


def test_bwrap_available_is_bool() -> None:
    """Just smoke-check the type — actual availability depends on host."""
    assert isinstance(bwrap_available(), bool)


def test_wrap_command_resolves_project_path(tmp_path: Path) -> None:
    """A path passed with `..` or symlinks must be resolved before binding —
    otherwise bwrap binds a confusing path and the sandbox `--chdir` lands
    in the wrong place."""
    sub = tmp_path / "a"
    sub.mkdir()
    weird = sub / ".." / "a"
    argv = wrap_command_with_bwrap("pwd", weird)
    resolved = str(sub.resolve())
    assert resolved in argv

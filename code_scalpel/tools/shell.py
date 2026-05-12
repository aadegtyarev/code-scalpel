from __future__ import annotations

import asyncio
from typing import NamedTuple, Protocol, runtime_checkable

DEFAULT_WHITELIST: frozenset[str] = frozenset({"git", "pytest", "python", "python3", "rg"})


class ShellResult(NamedTuple):
    stdout: str
    returncode: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandNotAllowedError(Exception):
    pass


@runtime_checkable
class ShellRunner(Protocol):
    async def run(
        self, cmd: list[str], cwd: str | None = None, timeout: int = 30
    ) -> ShellResult: ...

    async def run_shell(
        self, command: str, cwd: str | None = None, timeout: int = 30
    ) -> ShellResult:
        """Run `command` through the shell — pipes / redirects / quoting
        all work. Bypasses the whitelist (`run`'s safety rail) because
        shell_exec policy is enforced one layer up by
        `code_scalpel.policy.decide`. Tests mock this to assert on the
        raw command string the agent emitted."""
        ...


class AsyncShellRunner:
    def __init__(self, whitelist: frozenset[str] = DEFAULT_WHITELIST) -> None:
        self._whitelist = whitelist

    async def run(self, cmd: list[str], cwd: str | None = None, timeout: int = 30) -> ShellResult:
        if not cmd:
            raise ValueError("cmd must not be empty")
        self._check_whitelist(cmd)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            raise
        return ShellResult(
            stdout=stdout.decode(errors="replace"),
            returncode=proc.returncode if proc.returncode is not None else 0,
        )

    async def run_shell(
        self, command: str, cwd: str | None = None, timeout: int = 30
    ) -> ShellResult:
        """Run `command` through `/bin/sh -c`. No whitelist — shell_exec
        policy is enforced upstream by `code_scalpel.policy.decide`."""
        if not command.strip():
            raise ValueError("command must not be empty")
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            raise
        return ShellResult(
            stdout=stdout.decode(errors="replace"),
            returncode=proc.returncode if proc.returncode is not None else 0,
        )

    def _check_whitelist(self, cmd: list[str]) -> None:
        executable = cmd[0].rsplit("/", 1)[-1]
        if executable not in self._whitelist:
            raise CommandNotAllowedError(
                f"'{executable}' is not allowed. Whitelist: {sorted(self._whitelist)}"
            )

"""GoSkill — `go test` / `go vet` / `gofmt` defaults for a Go project.

Detection is `go.mod` — modules-mode is the only flavour worth
supporting today; GOPATH-style trees are deprecated.

Commands use the modern toolchain: `go test ./...` for the whole
module, `go vet ./...` for the canonical static check (covers a lot of
what golangci-lint runs, available without extra installs), and
`gofmt -w .` for in-place formatting (built-in, no extra deps).
"""

from __future__ import annotations

import shlex
from pathlib import Path

from code_scalpel.skills.base import Skill


class GoSkill(Skill):
    name = "go"
    description = "go test / go vet / gofmt for a Go module (detects go.mod)."

    def detect(self, root: Path) -> bool:
        return (root / "go.mod").is_file()

    def test_cmd(self, args: str = "") -> list[str]:
        extra = shlex.split(args) if args else []
        # `-count=1` defeats Go's aggressive test-result caching — the
        # agent re-running tests after a patch wants fresh results, not
        # "PASS (cached)" from before the change.
        return ["go", "test", "-count=1", *extra, "./..."]

    def lint_cmd(self) -> list[str]:
        return ["go", "vet", "./..."]

    def format_cmd(self) -> list[str] | None:
        return ["gofmt", "-w", "."]

    def model_instructions(self) -> str:
        return """\
Go project rules:
- Tests: `go test -count=1 ./...` (`-count=1` defeats caching — always fresh)
- Lint: `go vet ./...`
- Format: `gofmt -w .`
- Test fails → read the output, fix the code, rerun\
"""

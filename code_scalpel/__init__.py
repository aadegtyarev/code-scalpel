"""code-scalpel — TUI coding agent for weak local LLMs.

`__version__` reads from the installed package metadata (pyproject.toml
is the single source of truth). Falls back to "0.0.0+local" when the
package isn't installed — e.g. running from a checkout without
`pip install -e .` first."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("code-scalpel")
except PackageNotFoundError:
    __version__ = "0.0.0+local"

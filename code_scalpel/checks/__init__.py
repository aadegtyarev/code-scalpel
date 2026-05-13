"""Static checks the agent runs without an LLM round-trip.

Each check answers a yes/no question about a file's structure
(does this test exercise anything? does this import resolve?). The
answers are deterministic, cheap, and immune to prompt drift — the
counterpart to v0.8's narrow LLM passes, which are slower but can
reason about behaviour.

v0.9 thesis: if a machine can verify it, the prompt shouldn't have
to ask for it.
"""

from __future__ import annotations

from code_scalpel.checks.empty_tests import EmptyTest, detect_empty_tests

__all__ = ["EmptyTest", "detect_empty_tests"]

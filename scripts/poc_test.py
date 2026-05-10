"""PoC validation: ask qwen2.5-coder-14b to produce a patch and check it applies."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from code_scalpel.agent import StepAgent
from code_scalpel.config import AgentConfig, AppConfig, ModelProfile
from code_scalpel.llm.adapter import OpenAICompatibleAdapter
from code_scalpel.patch.applier import apply_patch
from code_scalpel.tools.shell import AsyncShellRunner

_CONFIG = AppConfig(
    profiles={
        "local": ModelProfile(
            provider="lmstudio",
            model="qwen/qwen2.5-coder-14b",
            temperature=0.1,
            seed=42,
        )
    },
    agent=AgentConfig(max_files=3, max_file_lines=100),
)

_SAMPLE_CODE = """\
def add(a, b):
    return a + b


def subtract(a, b):
    return a - b
"""

_TASK = "Add type hints to both functions. Use int for all parameters and return types."


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)

        # init git repo so git apply works
        runner = AsyncShellRunner()
        await runner.run(["git", "init"], cwd=tmp)
        await runner.run(["git", "config", "user.email", "test@test.com"], cwd=tmp)
        await runner.run(["git", "config", "user.name", "Test"], cwd=tmp)

        (cwd / "math_utils.py").write_text(_SAMPLE_CODE)
        await runner.run(["git", "add", "."], cwd=tmp)
        await runner.run(["git", "commit", "-m", "init"], cwd=tmp)

        profile = _CONFIG.current_profile
        llm = OpenAICompatibleAdapter(
            base_url=f"{profile.provider_base_url()}/v1",
            api_key=profile.api_key(),
            model=profile.model,
            cost_per_1k=profile.cost_per_1k,
        )
        agent = StepAgent(llm=llm, cwd=cwd, config=_CONFIG)

        print(f"Task: {_TASK}")
        print("Calling model...")

        result = await agent.ask(_TASK)

        print(f"\n--- Model response ({result.response.completion_tokens} tokens) ---")
        print(result.reply[:800])

        if result.patch is None:
            print("\n✗ FAIL: no valid diff extracted from response")
            sys.exit(1)

        print(f"\n--- Extracted patch ({len(result.patch)} chars) ---")
        print(result.patch[:400])

        apply_result = await apply_patch(result.patch, runner, cwd)
        if apply_result.ok:
            patched = (cwd / "math_utils.py").read_text()
            print("\n--- Patched file ---")
            print(patched)
            has_hints = "int" in patched or ":" in patched
            print(
                f"\n{'✓ PASS' if has_hints else '✗ FAIL'}: patch applied, type hints present: {has_hints}"
            )
        else:
            print(f"\n✗ FAIL: git apply failed:\n{apply_result.stdout}")
            sys.exit(1)


asyncio.run(main())

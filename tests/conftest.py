from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-llm",
        action="store_true",
        default=False,
        help="Run @pytest.mark.llm tests against a real local model (LM Studio).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-llm"):
        return
    skip_llm = pytest.mark.skip(reason="LLM tests skipped — pass --run-llm to enable.")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip_llm)

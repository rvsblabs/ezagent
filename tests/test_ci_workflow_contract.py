"""Ensure .github/workflows/ci.yml keeps required integration env (when present)."""

from pathlib import Path

import pytest

from tests.ci_integration_env_contract import INTEGRATION_CI_STEP_ENV_VARS


def test_github_ci_integration_step_sets_contract_env_vars():
    """If CI workflow exists, Integration tests step must declare all contract env keys."""
    root = Path(__file__).resolve().parents[1]
    workflow = root / ".github/workflows/ci.yml"
    if not workflow.is_file():
        pytest.skip("No .github/workflows/ci.yml — add workflow or ignore until CI lands")

    text = workflow.read_text()
    marker = "- name: Integration tests"
    if marker not in text:
        pytest.fail(f"{workflow}: expected step {marker!r}")

    idx = text.index(marker)
    rest = text[idx:]
    # Stop at next "\n      - name:" (next top-level step in jobs.test.steps)
    end = rest.find("\n      - name:", 1)
    step_block = rest if end == -1 else rest[:end]

    missing = sorted(k for k in INTEGRATION_CI_STEP_ENV_VARS if f"{k}:" not in step_block)
    assert not missing, (
        f"{workflow}: Integration tests step missing env keys {missing}. "
        f"See tests/ci_integration_env_contract.py and AGENTS.md (CI integration environment)."
    )

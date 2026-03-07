"""Tests for eval: score(), load_eval_dataset(), run_eval_async()."""
from pathlib import Path

import pytest
import yaml

from ezagent.eval import EvalCase, EvalResult, load_eval_dataset, run_eval_async, score


# ---------------------------------------------------------------------------
# score()
# ---------------------------------------------------------------------------


def test_score_substring_pass():
    assert score("The answer is 42.", "42", "substring") is True


def test_score_substring_fail():
    assert score("No answer here.", "42", "substring") is False


def test_score_exact_pass():
    assert score("  4  ", "4", "exact") is True


def test_score_exact_fail():
    assert score("The answer is 4.", "4", "exact") is False


def test_score_regex_pass():
    assert score("AI made a breakthrough", r"AI.*breakthrough", "regex") is True


def test_score_regex_case_insensitive():
    assert score("ai news today", "AI", "regex") is True


def test_score_regex_fail():
    assert score("nothing relevant", r"^AI$", "regex") is False


def test_score_unknown_scorer_defaults_to_substring():
    # Unknown scorer falls back to substring
    assert score("hello world", "world", "fuzzy_unknown") is True


# ---------------------------------------------------------------------------
# load_eval_dataset()
# ---------------------------------------------------------------------------


def test_load_eval_dataset(tmp_path):
    """load_eval_dataset parses YAML and returns (agent_name, cases)."""
    eval_data = {
        "agent": "reporter",
        "cases": [
            {
                "id": "case1",
                "input": "What is AI?",
                "expected": "AI",
                "scorer": "substring",
                "fixture": "fixtures/case1.yml",
            },
            {
                "id": "case2",
                "input": "2+2?",
                "expected": "4",
                "scorer": "exact",
            },
        ],
    }
    eval_file = tmp_path / "eval.yml"
    with open(eval_file, "w") as f:
        yaml.dump(eval_data, f)

    agent_name, cases = load_eval_dataset(eval_file)
    assert agent_name == "reporter"
    assert len(cases) == 2
    assert cases[0].id == "case1"
    assert cases[0].input == "What is AI?"
    assert cases[0].expected == "AI"
    assert cases[0].scorer == "substring"
    assert cases[0].fixture == "fixtures/case1.yml"
    assert cases[1].id == "case2"
    assert cases[1].scorer == "exact"
    assert cases[1].fixture is None


def test_load_eval_dataset_defaults_to_substring(tmp_path):
    """load_eval_dataset uses substring as default scorer."""
    eval_data = {
        "agent": "test",
        "cases": [{"id": "c1", "input": "hi", "expected": "hello"}],
    }
    eval_file = tmp_path / "eval.yml"
    with open(eval_file, "w") as f:
        yaml.dump(eval_data, f)

    _, cases = load_eval_dataset(eval_file)
    assert cases[0].scorer == "substring"


# ---------------------------------------------------------------------------
# run_eval_async() with mock fixtures
# ---------------------------------------------------------------------------


def _make_fixture(tmp_path: Path, name: str, llm_text: str) -> Path:
    """Helper: create a minimal fixture file."""
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir(exist_ok=True)
    fixture_data = {
        "agent": "assistant",
        "input": "test",
        "llm_calls": [{"text": llm_text, "tool_calls": [], "stop_reason": "end_turn"}],
        "tool_calls": {},
    }
    path = fixture_dir / f"{name}.yml"
    with open(path, "w") as f:
        yaml.dump(fixture_data, f)
    return path


@pytest.mark.asyncio
async def test_run_eval_async_passing_case(tmp_path):
    """run_eval_async marks case as passed when output contains expected substring."""
    from ezagent.config import AgentConfig, ProjectConfig

    fixture_path = _make_fixture(tmp_path, "pass_case", "The answer is 42.")

    eval_data = {
        "agent": "assistant",
        "cases": [
            {
                "id": "math",
                "input": "What is 6x7?",
                "expected": "42",
                "scorer": "substring",
                "fixture": f"fixtures/pass_case.yml",
            }
        ],
    }
    eval_file = tmp_path / "eval.yml"
    with open(eval_file, "w") as f:
        yaml.dump(eval_data, f)

    config = ProjectConfig(
        agents={"assistant": AgentConfig(tools=[], skills=[], description="")},
        project_dir=tmp_path,
    )
    results = await run_eval_async(eval_file, config, False)
    assert len(results) == 1
    assert results[0].case_id == "math"
    assert results[0].passed is True
    assert results[0].output == "The answer is 42."
    assert results[0].error is None


@pytest.mark.asyncio
async def test_run_eval_async_failing_case(tmp_path):
    """run_eval_async marks case as failed when output does not match."""
    from ezagent.config import AgentConfig, ProjectConfig

    _make_fixture(tmp_path, "fail_case", "I don't know.")

    eval_data = {
        "agent": "assistant",
        "cases": [
            {
                "id": "tricky",
                "input": "What is 6x7?",
                "expected": "42",
                "scorer": "exact",
                "fixture": "fixtures/fail_case.yml",
            }
        ],
    }
    eval_file = tmp_path / "eval.yml"
    with open(eval_file, "w") as f:
        yaml.dump(eval_data, f)

    config = ProjectConfig(
        agents={"assistant": AgentConfig(tools=[], skills=[], description="")},
        project_dir=tmp_path,
    )
    results = await run_eval_async(eval_file, config, False)
    assert results[0].passed is False
    assert results[0].error is None


@pytest.mark.asyncio
async def test_run_eval_async_missing_fixture_error(tmp_path):
    """run_eval_async records error when fixture file is missing."""
    from ezagent.config import AgentConfig, ProjectConfig

    eval_data = {
        "agent": "assistant",
        "cases": [
            {
                "id": "broken",
                "input": "hi",
                "expected": "hello",
                "fixture": "fixtures/nonexistent.yml",
            }
        ],
    }
    eval_file = tmp_path / "eval.yml"
    with open(eval_file, "w") as f:
        yaml.dump(eval_data, f)

    config = ProjectConfig(
        agents={"assistant": AgentConfig(tools=[], skills=[], description="")},
        project_dir=tmp_path,
    )
    results = await run_eval_async(eval_file, config, False)
    assert results[0].passed is False
    assert results[0].error is not None


@pytest.mark.asyncio
async def test_run_eval_async_multiple_cases(tmp_path):
    """run_eval_async processes multiple cases and returns all results."""
    from ezagent.config import AgentConfig, ProjectConfig

    _make_fixture(tmp_path, "case_a", "Paris is the capital of France.")
    _make_fixture(tmp_path, "case_b", "I have no idea about that math problem.")

    eval_data = {
        "agent": "assistant",
        "cases": [
            {
                "id": "capitals",
                "input": "Capital of France?",
                "expected": "Paris",
                "scorer": "substring",
                "fixture": "fixtures/case_a.yml",
            },
            {
                "id": "math",
                "input": "9 x 11?",
                "expected": "99",
                "scorer": "substring",
                "fixture": "fixtures/case_b.yml",
            },
        ],
    }
    eval_file = tmp_path / "eval.yml"
    with open(eval_file, "w") as f:
        yaml.dump(eval_data, f)

    config = ProjectConfig(
        agents={"assistant": AgentConfig(tools=[], skills=[], description="")},
        project_dir=tmp_path,
    )
    results = await run_eval_async(eval_file, config, False)
    assert len(results) == 2
    assert results[0].passed is True   # "Paris" in "Paris is the capital of France."
    assert results[1].passed is False  # "99" not in "I have no idea about that math problem."

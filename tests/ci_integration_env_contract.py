"""Env var names the GitHub Actions integration step must set.

Orchestration/discussion code paths read EZAGENT_TEST_* from the daemon environment.
Fixtures often set them per-daemon; the CI job must still set them so any subprocess
that copies os.environ without overrides never hits live LLMs.

Keep in sync with AGENTS.md (CI integration environment) and .github/workflows/ci.yml.
"""

INTEGRATION_CI_STEP_ENV_VARS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "EZAGENT_TEST_PLANNER_RESPONSE",
        "EZAGENT_TEST_ORCHESTRATION_FINAL",
        "EZAGENT_TEST_DISCUSSION_DECISION",
    }
)

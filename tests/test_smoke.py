"""Smoke tests to verify the ezagent package imports and CLI entry point work."""

import importlib

import pytest
from click.testing import CliRunner

from ezagent.cli import cli


def test_package_imports():
    for mod in (
        "ezagent.cli",
        "ezagent.config",
        "ezagent.agent",
        "ezagent.daemon",
        "ezagent.event_log",
        "ezagent.scaffold",
        "ezagent.discussion",
        "ezagent.orchestration",
        "ezagent.llm",
        "ezagent.tools.manager",
    ):
        importlib.import_module(mod)


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.output


def test_cli_tools():
    runner = CliRunner()
    result = runner.invoke(cli, ["tools"])
    assert result.exit_code == 0
    assert "memory" in result.output

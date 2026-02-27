"""Tests for ez update-docs adding Docker scaffold files to existing projects."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from ezagent.cli import cli


def _make_project(tmp_path: Path) -> Path:
    """Minimal existing project (no Docker files)."""
    (tmp_path / "agents.yml").write_text(
        "provider: anthropic\nagents:\n  assistant:\n    description: test\n"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Creates missing Docker files
# ---------------------------------------------------------------------------

def test_update_docs_creates_dockerfile_if_missing(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    assert result.exit_code == 0
    assert (tmp_path / "Dockerfile").is_file()


def test_update_docs_creates_docker_compose_if_missing(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    assert result.exit_code == 0
    assert (tmp_path / "docker-compose.yml").is_file()


def test_update_docs_creates_dockerignore_if_missing(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    assert result.exit_code == 0
    assert (tmp_path / ".dockerignore").is_file()


def test_update_docs_creates_env_example_if_missing(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    assert result.exit_code == 0
    assert (tmp_path / ".env.example").is_file()


# ---------------------------------------------------------------------------
# Created files have correct content
# ---------------------------------------------------------------------------

def test_update_docs_dockerfile_content(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    content = (tmp_path / "Dockerfile").read_text()
    assert "ghcr.io/astral-sh/uv" in content
    assert "ezagent[serve]" in content


def test_update_docs_docker_compose_content(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    content = (tmp_path / "docker-compose.yml").read_text()
    assert "daemon:" in content
    assert "api:" in content
    assert "7771" in content


def test_update_docs_env_example_content(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    content = (tmp_path / ".env.example").read_text()
    assert "ANTHROPIC_API_KEY" in content


# ---------------------------------------------------------------------------
# Does NOT overwrite existing Docker files
# ---------------------------------------------------------------------------

def test_update_docs_does_not_overwrite_existing_dockerfile(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    original = "# my custom Dockerfile\n"
    (tmp_path / "Dockerfile").write_text(original)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    assert (tmp_path / "Dockerfile").read_text() == original


def test_update_docs_does_not_overwrite_existing_docker_compose(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    original = "# my custom compose\n"
    (tmp_path / "docker-compose.yml").write_text(original)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    assert (tmp_path / "docker-compose.yml").read_text() == original


def test_update_docs_does_not_overwrite_existing_dockerignore(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    original = "my-secrets/\n"
    (tmp_path / ".dockerignore").write_text(original)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    assert (tmp_path / ".dockerignore").read_text() == original


def test_update_docs_does_not_overwrite_existing_env_example(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    original = "MY_CUSTOM_KEY=abc\n"
    (tmp_path / ".env.example").write_text(original)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    assert (tmp_path / ".env.example").read_text() == original


# ---------------------------------------------------------------------------
# CLI output messages
# ---------------------------------------------------------------------------

def test_update_docs_output_says_created_dockerfile(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    assert "Dockerfile" in result.output
    assert "Created" in result.output


def test_update_docs_output_says_skipping_existing_dockerfile(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    (tmp_path / "Dockerfile").write_text("# existing\n")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    assert "Dockerfile" in result.output
    assert "skipping" in result.output


def test_update_docs_output_says_skipping_existing_docker_compose(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    (tmp_path / "docker-compose.yml").write_text("# existing\n")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    assert "docker-compose.yml" in result.output
    assert "skipping" in result.output


# ---------------------------------------------------------------------------
# Existing behaviour preserved: CLAUDE.md still updated
# ---------------------------------------------------------------------------

def test_update_docs_still_updates_claude_md(tmp_path: Path, monkeypatch):
    _make_project(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# old content\n")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["update-docs"], catch_exceptions=False)
    assert result.exit_code == 0
    assert (tmp_path / "CLAUDE.md").read_text() != "# old content\n"
    assert "Updated" in result.output


def test_update_docs_outside_project_fails(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no agents.yml
    runner = CliRunner()
    result = runner.invoke(cli, ["update-docs"])
    assert result.exit_code != 0

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlparse

GIT_PREFIX = "git+"


def is_git_ref(name: str) -> bool:
    """Check if a tool/skill name is a git URL reference."""
    return name.startswith(GIT_PREFIX)


def _repo_short_name(url: str) -> str:
    """Derive a short name from a git URL (repo name without .git)."""
    parsed = urlparse(url)
    # e.g. /user/my-tool.git -> my-tool
    basename = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if basename.endswith(".git"):
        basename = basename[:-4]
    return basename


def _clone_or_pull(url: str, dest: Path) -> None:
    """Clone a repo (shallow) or pull if already cached."""
    if (dest / ".git").is_dir():
        subprocess.run(
            ["git", "-C", str(dest), "pull", "--ff-only"],
            check=True,
            capture_output=True,
        )
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            check=True,
            capture_output=True,
        )


def _ensure_gitignore(project_dir: Path) -> None:
    """Add .ezagent/ to project .gitignore if not already present."""
    gitignore = project_dir / ".gitignore"
    marker = ".ezagent/"
    if gitignore.is_file():
        content = gitignore.read_text()
        if marker in content:
            return
        # Append with a newline separator if file doesn't end with one
        if content and not content.endswith("\n"):
            content += "\n"
        content += marker + "\n"
        gitignore.write_text(content)
    else:
        gitignore.write_text(marker + "\n")


def resolve_externals(
    project_dir: Path,
    tool_names: List[str],
    skill_names: List[str],
) -> Tuple[Dict[str, Path], Dict[str, Path], List[str], List[str]]:
    """Resolve git-based external tools and skills.

    Returns:
        (external_tool_paths, external_skill_paths, local_tool_names, local_skill_names)
    """
    external_tool_paths: Dict[str, Path] = {}
    external_skill_paths: Dict[str, Path] = {}
    local_tools: List[str] = []
    local_skills: List[str] = []
    needs_gitignore = False

    for name in tool_names:
        if is_git_ref(name):
            url = name[len(GIT_PREFIX):]
            short = _repo_short_name(url)
            dest = project_dir / ".ezagent" / "external" / "tools" / short
            _clone_or_pull(url, dest)
            external_tool_paths[short] = dest
            needs_gitignore = True
        else:
            local_tools.append(name)

    for name in skill_names:
        if is_git_ref(name):
            url = name[len(GIT_PREFIX):]
            short = _repo_short_name(url)
            dest = project_dir / ".ezagent" / "external" / "skills" / short
            _clone_or_pull(url, dest)
            external_skill_paths[short] = dest
            needs_gitignore = True
        else:
            local_skills.append(name)

    if needs_gitignore:
        _ensure_gitignore(project_dir)

    return external_tool_paths, external_skill_paths, local_tools, local_skills

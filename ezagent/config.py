from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, field_validator, model_validator


class AgentConfig(BaseModel):
    tools: List[str] = []
    skills: List[str] = []
    description: str = ""

    @field_validator("tools", "skills", mode="before")
    @classmethod
    def split_csv(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


class ProjectConfig(BaseModel):
    agents: Dict[str, AgentConfig]
    project_dir: Path

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def validate_project(self):
        agent_names = set(self.agents.keys())
        tools_dir = self.project_dir / "tools"
        skills_dir = self.project_dir / "skills"

        for name, agent in self.agents.items():
            # Validate skills exist as .md files
            for skill in agent.skills:
                skill_path = skills_dir / f"{skill}.md"
                if not skill_path.is_file():
                    raise ValueError(
                        f"Agent '{name}': skill file not found: {skill_path}"
                    )

            # Validate tools: each must be either a tool dir or another agent name
            for tool in agent.tools:
                if tool in agent_names:
                    continue
                tool_main = tools_dir / tool / "main.py"
                if not tool_main.is_file():
                    raise ValueError(
                        f"Agent '{name}': tool '{tool}' is neither an agent "
                        f"nor a tool directory with main.py at {tool_main}"
                    )

            # Check for self-reference
            if name in agent.tools:
                raise ValueError(f"Agent '{name}' lists itself as a tool")

        # Check for circular agent references (simple DFS)
        def _has_cycle(agent_name: str, visited: set, stack: set) -> bool:
            visited.add(agent_name)
            stack.add(agent_name)
            for tool in self.agents[agent_name].tools:
                if tool in agent_names:
                    if tool in stack:
                        return True
                    if tool not in visited and _has_cycle(tool, visited, stack):
                        return True
            stack.discard(agent_name)
            return False

        visited: set = set()
        for agent_name in agent_names:
            if agent_name not in visited:
                if _has_cycle(agent_name, visited, set()):
                    raise ValueError(
                        f"Circular agent reference detected involving '{agent_name}'"
                    )

        return self

    @property
    def socket_path(self) -> str:
        h = hashlib.md5(str(self.project_dir.resolve()).encode()).hexdigest()[:12]
        return f"/tmp/ezagent_{h}.sock"

    @property
    def pid_path(self) -> str:
        h = hashlib.md5(str(self.project_dir.resolve()).encode()).hexdigest()[:12]
        return f"/tmp/ezagent_{h}.pid"


def find_project_dir() -> Optional[Path]:
    """Walk up from cwd to find a directory containing agents.yml."""
    current = Path.cwd()
    while True:
        if (current / "agents.yml").is_file():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def load_config(project_dir: Optional[Path] = None) -> ProjectConfig:
    """Load and validate project configuration from agents.yml."""
    if project_dir is None:
        project_dir = find_project_dir()
    if project_dir is None:
        raise FileNotFoundError(
            "No agents.yml found in current directory or any parent directory."
        )

    yml_path = project_dir / "agents.yml"
    with open(yml_path) as f:
        raw = yaml.safe_load(f)

    if not raw or "agents" not in raw:
        raise ValueError("agents.yml must contain an 'agents' key.")

    return ProjectConfig(agents=raw["agents"], project_dir=project_dir)

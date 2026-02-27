from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, field_validator, model_validator

from croniter import croniter

from ezagent.external import is_git_ref
from ezagent.tools.builtins import PREBUILT_TOOLS


class ScheduleEntry(BaseModel):
    cron: str
    message: str

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        if not croniter.is_valid(v):
            raise ValueError(f"Invalid cron expression: {v!r}")
        return v


class AgentConfig(BaseModel):
    tools: List[str] = []
    skills: List[str] = []
    description: str = ""
    provider: str = ""
    model: str = ""
    schedule: List[ScheduleEntry] = []

    @field_validator("tools", "skills", mode="before")
    @classmethod
    def split_csv(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


class DiscussantConfig(BaseModel):
    agent: str
    role: str = ""


class DiscussionConfig(BaseModel):
    participants: List[DiscussantConfig]
    max_rounds: int = 5
    max_tokens: int = 50_000
    max_duration: int = 300
    termination: str = "rounds"  # "rounds" | "consensus"
    moderator: Optional[str] = None
    on_deadlock: List[str] = ["moderator_decides"]
    # "moderator_decides" | "human_approval" | "record_and_move_on"
    schedule: List[ScheduleEntry] = []


VALID_ORCHESTRATION_PATTERNS = {"plan_and_delegate"}


class OrchestrationConfig(BaseModel):
    pattern: str
    planner: str
    workers: List[str] = []
    aggregator: Optional[str] = None
    parallel: bool = True

    @field_validator("workers", mode="before")
    @classmethod
    def split_workers(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        if v not in VALID_ORCHESTRATION_PATTERNS:
            raise ValueError(
                f"Orchestration pattern must be one of {sorted(VALID_ORCHESTRATION_PATTERNS)}, got {v!r}"
            )
        return v


class ProjectConfig(BaseModel):
    agents: Dict[str, AgentConfig]
    discussions: Dict[str, DiscussionConfig] = {}
    orchestrations: Dict[str, OrchestrationConfig] = {}
    project_dir: Path
    provider: str = "anthropic"
    model: str = ""
    timezone: str = "UTC"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError:
            raise ValueError(f"Unknown timezone: {v!r}. Use a valid IANA timezone name (e.g. 'America/New_York').")
        return v

    model_config = {"arbitrary_types_allowed": True}

    @model_validator(mode="after")
    def validate_project(self):
        agent_names = set(self.agents.keys())
        discussion_names = set(self.discussions.keys())
        orchestration_names = set(self.orchestrations.keys())
        tools_dir = self.project_dir / "tools"
        skills_dir = self.project_dir / "skills"

        for name, agent in self.agents.items():
            # Validate skills exist as .md files (skip git refs)
            for skill in agent.skills:
                if is_git_ref(skill):
                    continue
                skill_path = skills_dir / f"{skill}.md"
                if not skill_path.is_file():
                    raise ValueError(
                        f"Agent '{name}': skill file not found: {skill_path}"
                    )

            # Validate tools: each must be a tool dir, agent name, discussion name,
            # orchestration name, prebuilt, or git ref
            for tool in agent.tools:
                if is_git_ref(tool):
                    continue
                if tool in PREBUILT_TOOLS:
                    continue
                if tool in agent_names:
                    continue
                if tool in discussion_names:
                    continue
                if tool in orchestration_names:
                    continue
                tool_main = tools_dir / tool / "main.py"
                if not tool_main.is_file():
                    raise ValueError(
                        f"Agent '{name}': tool '{tool}' is neither an agent, "
                        f"a discussion, an orchestration, nor a tool directory with main.py at {tool_main}"
                    )

            # Check for self-reference
            if name in agent.tools:
                raise ValueError(f"Agent '{name}' lists itself as a tool")

        # Validate discussion configs
        valid_terminations = {"rounds", "consensus"}
        valid_deadlock_actions = {"moderator_decides", "human_approval", "record_and_move_on"}
        for disc_name, disc in self.discussions.items():
            if disc.termination not in valid_terminations:
                raise ValueError(
                    f"Discussion '{disc_name}': termination must be one of "
                    f"{valid_terminations}, got {disc.termination!r}"
                )
            for action in disc.on_deadlock:
                if action not in valid_deadlock_actions:
                    raise ValueError(
                        f"Discussion '{disc_name}': on_deadlock action must be one of "
                        f"{valid_deadlock_actions}, got {action!r}"
                    )
            for discussant in disc.participants:
                if discussant.agent not in agent_names:
                    raise ValueError(
                        f"Discussion '{disc_name}': participant agent "
                        f"'{discussant.agent}' is not defined"
                    )
            if disc.moderator is not None and disc.moderator not in agent_names:
                raise ValueError(
                    f"Discussion '{disc_name}': moderator '{disc.moderator}' is not defined"
                )

        # Validate orchestration configs
        for orch_name, orch in self.orchestrations.items():
            if orch.planner not in agent_names:
                raise ValueError(
                    f"Orchestration '{orch_name}': planner '{orch.planner}' is not defined"
                )
            for worker in orch.workers:
                if worker not in agent_names:
                    raise ValueError(
                        f"Orchestration '{orch_name}': worker '{worker}' is not defined"
                    )
            if orch.aggregator is not None and orch.aggregator not in agent_names:
                raise ValueError(
                    f"Orchestration '{orch_name}': aggregator '{orch.aggregator}' is not defined"
                )

        # Check for circular agent references (simple DFS)
        # Discussions are not included since they are not part of the agent graph
        def _has_cycle(agent_name: str, visited: set, stack: set) -> bool:
            visited.add(agent_name)
            stack.add(agent_name)
            for tool in self.agents[agent_name].tools:
                if is_git_ref(tool):
                    continue
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

    @property
    def events_db_path(self) -> Path:
        return self.project_dir / ".ezagent" / "events.db"


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

    return ProjectConfig(
        agents=raw["agents"],
        discussions=raw.get("discussions", {}),
        orchestrations=raw.get("orchestrations", {}),
        project_dir=project_dir,
        provider=raw.get("provider", "anthropic"),
        model=raw.get("model", ""),
        timezone=raw.get("timezone", "UTC"),
    )

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

from ezagent.config import DiscussionConfig
from ezagent.llm.base import LLMProvider

if TYPE_CHECKING:
    from ezagent.agent import Agent
    from ezagent.event_log import EventLogger


@dataclass
class Turn:
    agent_name: str
    role: str
    content: str
    round_number: int


@dataclass
class DiscussionResult:
    topic: str
    discussion_name: str
    terminal_state: str  # full_consensus | majority | deadlock_resolved | unresolved | pending_human
    decision: str
    dissent: Optional[str]
    transcript: List[Turn]
    rounds_completed: int


class DiscussionRuntime:
    """
    Orchestrates a structured multi-turn discussion between named agents.

    Each round every participant receives the full transcript so far and adds
    a turn. After each round the runtime checks for convergence (when
    termination="consensus") and position drift. Hard limits on rounds,
    tokens, and wall-clock time provide circuit-breaker behaviour.
    """

    def __init__(
        self,
        name: str,
        config: DiscussionConfig,
        agents: Dict[str, "Agent"],
        checker_provider: LLMProvider,
        event_logger: Optional["EventLogger"] = None,
    ):
        self.name = name
        self.config = config
        self.agents = agents
        self.checker = checker_provider
        self._event_logger = event_logger
        self.transcript: List[Turn] = []

    async def run(self, topic: str) -> DiscussionResult:
        start = time.monotonic()

        # Start event log entry
        discussion_uuid: Optional[str] = None
        if self._event_logger is not None:
            discussion_uuid = await self._event_logger.start_discussion(self.name, topic)

        stub_decision = os.environ.get("EZAGENT_TEST_DISCUSSION_DECISION")
        if stub_decision is not None:
            stub_result = DiscussionResult(
                topic=topic,
                discussion_name=self.name,
                terminal_state="integration_stub",
                decision=stub_decision,
                dissent=None,
                transcript=[],
                rounds_completed=0,
            )
            if self._event_logger is not None and discussion_uuid is not None:
                self._event_logger.finish_discussion(
                    discussion_uuid,
                    terminal_state=stub_result.terminal_state,
                    decision=stub_result.decision,
                    dissent=stub_result.dissent,
                    rounds=stub_result.rounds_completed,
                )
            return stub_result

        # Maps agent_name -> content of their last turn, for drift detection
        prev_positions: Dict[str, str] = {}

        result: Optional[DiscussionResult] = None
        for round_num in range(1, self.config.max_rounds + 1):

            # --- wall-clock guard ---
            if time.monotonic() - start > self.config.max_duration:
                result = await self._escalate(topic, "timeout")
                break

            # --- each participant takes a turn ---
            for discussant in self.config.participants:
                prompt = self._build_turn_prompt(
                    topic, discussant.agent, discussant.role, round_num
                )
                agent_result = await self.agents[discussant.agent].run(
                    prompt,
                    source="discussion",
                    parent_run_uuid=discussion_uuid,
                )
                turn = Turn(
                    agent_name=discussant.agent,
                    role=discussant.role,
                    content=agent_result.text,
                    round_number=round_num,
                )
                self.transcript.append(turn)
                if self._event_logger is not None and discussion_uuid is not None:
                    self._event_logger.log_discussion_turn(
                        discussion_uuid,
                        discussant.agent,
                        discussant.role,
                        agent_result.text,
                        round_num,
                    )

            # --- token budget guard ---
            if self._approx_tokens() > self.config.max_tokens:
                result = await self._escalate(topic, "token_limit")
                break

            # --- convergence + drift checks (only when termination="consensus") ---
            if self.config.termination == "consensus":
                check = await self._check_convergence()

                if check["converged"]:
                    dissenters = check.get("dissenters") or []
                    result = DiscussionResult(
                        topic=topic,
                        discussion_name=self.name,
                        terminal_state=check.get("type", "full_consensus"),
                        decision=check.get("summary", ""),
                        dissent=", ".join(dissenters) if dissenters else None,
                        transcript=self.transcript,
                        rounds_completed=round_num,
                    )
                    break

                # Positions frozen across two consecutive rounds → deadlock
                curr_positions = self._latest_positions()
                if prev_positions and curr_positions == prev_positions:
                    result = await self._escalate(topic, "frozen")
                    break
                prev_positions = curr_positions

        if result is None:
            # --- max rounds exhausted ---
            if self.config.termination == "rounds":
                # Expected happy path: moderator synthesises from the full transcript
                result = await self._moderator_synthesis(topic, reason=None)
            else:
                # consensus mode that never converged and wasn't caught by drift/timeout
                result = await self._escalate(topic, "max_rounds")

        if self._event_logger is not None and discussion_uuid is not None:
            self._event_logger.finish_discussion(
                discussion_uuid,
                terminal_state=result.terminal_state,
                decision=result.decision,
                dissent=result.dissent,
                rounds=result.rounds_completed,
                status="success",
            )

        return result

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _build_turn_prompt(
        self, topic: str, agent_name: str, role: str, round_num: int
    ) -> str:
        """
        Build the per-turn prompt injected into the agent's run() call.

        The role is re-stated every turn to resist the social-pressure drift
        that LLMs exhibit when they see everyone else agreeing.
        """
        lines: List[str] = []

        if role:
            lines.append(f"Your role in this discussion: {role}")
            lines.append(
                "Stay true to this role. Do not agree simply because others have — "
                "only shift your position if the evidence or arguments genuinely warrant it."
            )

        lines.append(f"\nDiscussion topic: {topic}")
        lines.append(f"Round {round_num} of {self.config.max_rounds}\n")

        if self.transcript:
            lines.append("=== Discussion so far ===")
            for turn in self.transcript:
                lines.append(
                    f"\n[{turn.agent_name}] (Round {turn.round_number}):\n{turn.content}"
                )
            lines.append("\n=== End of transcript ===\n")

        lines.append(
            f"It is now your turn ({agent_name}). "
            "Respond to the discussion. Be direct and concise."
        )
        return "\n".join(lines)

    async def _check_convergence(self) -> dict:
        """
        Cheap, tool-free LLM call that reads the transcript and returns JSON.
        Uses the checker_provider (intended to be a small/fast model).
        """
        transcript_text = "\n\n".join(
            f"[{t.agent_name}] Round {t.round_number}:\n{t.content}"
            for t in self.transcript
        )
        prompt = (
            "Read this discussion transcript and determine whether the participants "
            "have reached sufficient agreement to make a decision.\n\n"
            f"{transcript_text}\n\n"
            "Reply with JSON only — no other text:\n"
            "{\n"
            '  "converged": true or false,\n'
            '  "type": "full_consensus" or "majority" or "deadlock",\n'
            '  "summary": "one sentence on where they landed or why they are stuck",\n'
            '  "dissenters": ["agent_name"]\n'
            "}"
        )

        response = await self.checker.chat(
            messages=[{"role": "user", "content": prompt}],
            system="You are a neutral discussion analyst. Reply with valid JSON only.",
        )
        try:
            text = (
                response.text.strip()
                .removeprefix("```json")
                .removeprefix("```")
                .removesuffix("```")
                .strip()
            )
            return json.loads(text)
        except (json.JSONDecodeError, AttributeError):
            return {
                "converged": False,
                "type": "deadlock",
                "summary": "Could not parse convergence check response",
                "dissenters": [],
            }

    def _latest_positions(self) -> Dict[str, str]:
        """Return each agent's most recent turn content."""
        positions: Dict[str, str] = {}
        for turn in reversed(self.transcript):
            if turn.agent_name not in positions:
                positions[turn.agent_name] = turn.content
        return positions

    async def _escalate(self, topic: str, reason: str) -> DiscussionResult:
        """Work through the on_deadlock ladder until something resolves."""
        for action in self.config.on_deadlock:
            if action == "moderator_decides":
                return await self._moderator_synthesis(topic, reason)
            if action == "human_approval":
                return DiscussionResult(
                    topic=topic,
                    discussion_name=self.name,
                    terminal_state="pending_human",
                    decision=f"Deadlock ({reason}): awaiting human approval. "
                    "Resume with: ez discuss approve",
                    dissent=None,
                    transcript=self.transcript,
                    rounds_completed=self.transcript[-1].round_number
                    if self.transcript
                    else 0,
                )
            if action == "record_and_move_on":
                return DiscussionResult(
                    topic=topic,
                    discussion_name=self.name,
                    terminal_state="unresolved",
                    decision=f"No consensus reached ({reason})",
                    dissent=None,
                    transcript=self.transcript,
                    rounds_completed=self.transcript[-1].round_number
                    if self.transcript
                    else 0,
                )

        # Fallback if on_deadlock is empty
        return DiscussionResult(
            topic=topic,
            discussion_name=self.name,
            terminal_state="unresolved",
            decision=f"No consensus reached ({reason})",
            dissent=None,
            transcript=self.transcript,
            rounds_completed=self.transcript[-1].round_number if self.transcript else 0,
        )

    async def _moderator_synthesis(
        self, topic: str, reason: Optional[str]
    ) -> DiscussionResult:
        """
        The moderator reads the full transcript and issues a final decision.
        This is distinct from a normal participant turn: the moderator acts as
        a judge, not an advocate.
        """
        moderator_name = (
            self.config.moderator or self.config.participants[-1].agent
        )
        moderator = self.agents[moderator_name]

        transcript_text = "\n\n".join(
            f"[{t.agent_name}] Round {t.round_number}:\n{t.content}"
            for t in self.transcript
        )
        preamble = (
            f"The discussion ended without full consensus ({reason}). "
            if reason
            else "The discussion has completed. "
        )
        prompt = (
            f"{preamble}As moderator, you must now issue a final decision "
            "based on the discussion below.\n\n"
            f"Topic: {topic}\n\n"
            f"Transcript:\n{transcript_text}\n\n"
            "Provide your response in this format:\n"
            "DECISION: <one clear sentence>\n"
            "RATIONALE: <2-3 sentences>\n"
            "DISSENT: <minority views worth preserving, or 'none'>\n"
            "CONFIDENCE: <low | medium | high>"
        )

        result = await moderator.run(prompt)
        return DiscussionResult(
            topic=topic,
            discussion_name=self.name,
            terminal_state="deadlock_resolved" if reason else "full_consensus",
            decision=result.text,
            dissent=None,
            transcript=self.transcript,
            rounds_completed=self.transcript[-1].round_number if self.transcript else 0,
        )

    def _approx_tokens(self) -> int:
        """Rough token estimate: ~4 characters per token."""
        return sum(len(t.content) for t in self.transcript) // 4

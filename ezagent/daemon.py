from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import sys
from datetime import datetime, timezone
from typing import Any, Dict

import click
from croniter import croniter

from ezagent.agent import Agent, AgentResult
from ezagent.config import ProjectConfig, load_config
from ezagent.discussion import DiscussionResult, DiscussionRuntime
from ezagent.external import resolve_externals
from ezagent.llm import create_provider


class AgentDaemon:
    """Background daemon that hosts agents and listens on a Unix socket."""

    def __init__(self, config: ProjectConfig):
        self.config = config
        self.agents: Dict[str, Agent] = {}
        self._server: asyncio.AbstractServer | None = None
        self._scheduler_task: asyncio.Task | None = None
        self._schedule_entries: list[dict] = []
        self._checker_provider: Any = None  # reused for convergence checks

    async def initialize(self):
        """Create and initialize all agents."""
        agent_names = list(self.config.agents.keys())
        # Cache providers by (provider_name, model) to avoid duplicate clients
        provider_cache: Dict[tuple, Any] = {}

        for name, agent_config in self.config.agents.items():
            # Resolve external git-based tools and skills
            ext_tool_paths, ext_skill_paths, local_tools, local_skills = (
                resolve_externals(
                    self.config.project_dir,
                    agent_config.tools,
                    agent_config.skills,
                )
            )

            # Replace agent config lists with local-only names (git refs stripped)
            agent_config.tools = local_tools
            agent_config.skills = local_skills

            # Resolve provider and model: per-agent overrides project defaults
            provider_name = agent_config.provider or self.config.provider
            model = agent_config.model or self.config.model

            cache_key = (provider_name, model)
            if cache_key not in provider_cache:
                provider_cache[cache_key] = create_provider(provider_name, model)
            provider = provider_cache[cache_key]

            agent = Agent(
                name=name,
                config=agent_config,
                project_dir=self.config.project_dir,
                provider=provider,
                agent_names=agent_names,
                agent_runner=self._delegate_to_agent,
                external_tool_paths=ext_tool_paths,
                external_skill_paths=ext_skill_paths,
                discussion_runner=self._delegate_to_discussion,
                discussion_names=[
                    t for t in agent_config.tools
                    if t in self.config.discussions
                ],
            )
            await agent.initialize()
            self.agents[name] = agent

        # Create the convergence checker using the project's default provider.
        # Reuse from cache if already created, otherwise create fresh.
        checker_key = (self.config.provider, self.config.model)
        self._checker_provider = provider_cache.get(
            checker_key, create_provider(self.config.provider, self.config.model)
        )

        self._build_schedule()

    def _build_schedule(self):
        """Build the list of scheduled entries from agent and discussion configs."""
        now = datetime.now(timezone.utc)
        for name, agent_config in self.config.agents.items():
            for entry in agent_config.schedule:
                cron_iter = croniter(entry.cron, now)
                self._schedule_entries.append({
                    "kind": "agent",
                    "name": name,
                    "cron_expr": entry.cron,
                    "message": entry.message,
                    "cron_iter": cron_iter,
                    "next_run": cron_iter.get_next(datetime),
                })
        for name, disc_config in self.config.discussions.items():
            for entry in disc_config.schedule:
                cron_iter = croniter(entry.cron, now)
                self._schedule_entries.append({
                    "kind": "discussion",
                    "name": name,
                    "cron_expr": entry.cron,
                    "message": entry.message,  # becomes the topic
                    "cron_iter": cron_iter,
                    "next_run": cron_iter.get_next(datetime),
                })
        if self._schedule_entries:
            logging.info(
                "Scheduler initialized with %d entries", len(self._schedule_entries)
            )

    async def _run_scheduler(self):
        """Background loop that fires scheduled agent runs."""
        logging.info("Scheduler loop started")
        try:
            while True:
                if not self._schedule_entries:
                    await asyncio.sleep(60)
                    continue

                self._schedule_entries.sort(key=lambda e: e["next_run"])
                earliest = self._schedule_entries[0]["next_run"]
                now = datetime.now(timezone.utc)
                delay = (earliest - now).total_seconds()
                if delay > 0:
                    await asyncio.sleep(delay)

                now = datetime.now(timezone.utc)
                for entry in self._schedule_entries:
                    if entry["next_run"] <= now:
                        logging.info(
                            "Firing scheduled run: kind=%s name=%s cron=%r",
                            entry["kind"],
                            entry["name"],
                            entry["cron_expr"],
                        )
                        asyncio.create_task(
                            self._execute_scheduled_run(entry)
                        )
                        entry["next_run"] = entry["cron_iter"].get_next(datetime)
        except asyncio.CancelledError:
            logging.info("Scheduler loop cancelled")

    async def _execute_scheduled_run(self, entry: dict):
        """Execute a single scheduled run — either an agent message or a discussion."""
        kind = entry.get("kind", "agent")
        name = entry["name"]
        message = entry["message"]
        cron_expr = entry["cron_expr"]

        try:
            if kind == "discussion":
                logging.info(
                    "Firing scheduled discussion: name=%s cron=%r topic=%r",
                    name, cron_expr, message,
                )
                result = await self._run_discussion(name, message)
                logging.info(
                    "Scheduled discussion completed: name=%s state=%s",
                    name, result.get("terminal_state", "unknown"),
                )
            else:
                agent = self.agents.get(name)
                if agent is None:
                    logging.error("Scheduled run: agent %r not found", name)
                    return
                logging.info(
                    "Firing scheduled agent run: agent=%s cron=%r", name, cron_expr
                )
                result = await agent.run(message)
                logging.info(
                    "Scheduled run completed: agent=%s cron=%r result_length=%d",
                    name, cron_expr, len(result.text),
                )
        except Exception:
            logging.exception(
                "Scheduled run failed: kind=%s name=%s cron=%r", kind, name, cron_expr
            )

    async def _delegate_to_agent(
        self, agent_name: str, message: str, depth: int, debug: bool = False
    ) -> AgentResult:
        """Callback for agent-as-tool delegation."""
        agent = self.agents.get(agent_name)
        if agent is None:
            return AgentResult(text=json.dumps({"error": f"Agent '{agent_name}' not found"}))
        return await agent.run(message, depth=depth, debug=debug)

    async def _delegate_to_discussion(
        self, discussion_name: str, topic: str
    ) -> str:
        """Callback for discussion-as-tool: returns the decision text."""
        result = await self._run_discussion(discussion_name, topic)
        return result.get("decision", "Discussion produced no decision.")

    async def _run_discussion(self, discussion_name: str, topic: str) -> dict:
        """Run a named discussion and return a serialisable result dict."""
        disc_config = self.config.discussions.get(discussion_name)
        if disc_config is None:
            return {"error": f"Discussion '{discussion_name}' not found"}

        missing = [
            d.agent
            for d in disc_config.participants
            if d.agent not in self.agents
        ]
        if missing:
            return {"error": f"Discussion '{discussion_name}': unknown agents {missing}"}

        runtime = DiscussionRuntime(
            name=discussion_name,
            config=disc_config,
            agents=self.agents,
            checker_provider=self._checker_provider,
        )
        result: DiscussionResult = await runtime.run(topic)
        return {
            "terminal_state": result.terminal_state,
            "decision": result.decision,
            "dissent": result.dissent,
            "rounds_completed": result.rounds_completed,
            "transcript": [
                {
                    "agent": t.agent_name,
                    "round": t.round_number,
                    "content": t.content,
                }
                for t in result.transcript
            ],
        }

    async def start(self):
        """Start listening on Unix socket."""
        sock_path = self.config.socket_path

        # Clean up stale socket
        if os.path.exists(sock_path):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(1)
                s.connect(sock_path)
                s.close()
                # Socket is active — another daemon is running
                click.echo(f"Error: daemon already running (socket {sock_path} is active)")
                sys.exit(1)
            except (ConnectionRefusedError, OSError):
                # Stale socket — remove it
                os.unlink(sock_path)

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=sock_path
        )

        # Write PID file
        pid_path = self.config.pid_path
        with open(pid_path, "w") as f:
            f.write(str(os.getpid()))

        click.echo(f"Daemon started (PID {os.getpid()})")
        click.echo(f"Socket: {sock_path}")

        self._scheduler_task = asyncio.create_task(self._run_scheduler())

        async with self._server:
            await self._server.serve_forever()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """Handle a single client connection."""
        try:
            data = await reader.read(65536)
            if not data:
                writer.close()
                return

            request = json.loads(data.decode())

            # Handle status requests
            if request.get("type") == "status":
                agents_info = {}
                for name, agent in self.agents.items():
                    ac = self.config.agents[name]
                    provider_name = ac.provider or self.config.provider
                    model = ac.model or self.config.model
                    schedule_info = [
                        {
                            "cron": entry["cron_expr"],
                            "message": entry["message"],
                            "next_run": entry["next_run"].isoformat(),
                        }
                        for entry in self._schedule_entries
                        if entry["kind"] == "agent" and entry["name"] == name
                    ]
                    agents_info[name] = {
                        "description": ac.description,
                        "provider": provider_name,
                        "model": model,
                        "tools": ac.tools,
                        "skills": ac.skills,
                        "schedule": schedule_info,
                    }
                discussions_info = {}
                for name, dc in self.config.discussions.items():
                    schedule_info = [
                        {
                            "cron": entry["cron_expr"],
                            "message": entry["message"],
                            "next_run": entry["next_run"].isoformat(),
                        }
                        for entry in self._schedule_entries
                        if entry["kind"] == "discussion" and entry["name"] == name
                    ]
                    discussions_info[name] = {
                        "participants": [p.agent for p in dc.participants],
                        "termination": dc.termination,
                        "max_rounds": dc.max_rounds,
                        "moderator": dc.moderator,
                        "schedule": schedule_info,
                    }
                response = {"type": "status", "agents": agents_info, "discussions": discussions_info}
                writer.write((json.dumps(response) + "\n").encode())
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return

            if request.get("type") == "discuss":
                discussion_name = request.get("discussion", "")
                topic = request.get("topic", "")
                result = await self._run_discussion(discussion_name, topic)
                writer.write((json.dumps({"type": "discussion", **result}) + "\n").encode())
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return

            agent_name = request.get("agent", "")
            message = request.get("message", "")
            debug = request.get("debug", False)

            agent = self.agents.get(agent_name)
            if agent is None:
                response = {"type": "error", "text": f"Agent '{agent_name}' not found"}
                writer.write((json.dumps(response) + "\n").encode())
                await writer.drain()
                writer.close()
                return

            try:
                agent_result = await agent.run(message, debug=debug)
                # Stream debug events first
                if debug:
                    for event in agent_result.debug_events:
                        line = json.dumps({"type": "debug", "text": event})
                        writer.write((line + "\n").encode())
                        await writer.drain()
                response = {"type": "text", "text": agent_result.text}
            except Exception as e:
                response = {"type": "error", "text": f"Agent error: {e}"}

            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
        except Exception as e:
            try:
                err = {"type": "error", "text": f"Server error: {e}"}
                writer.write((json.dumps(err) + "\n").encode())
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def shutdown(self):
        """Stop server and disconnect all agents."""
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        if self._server:
            self._server.close()
        for agent in self.agents.values():
            await agent.shutdown()

        # Cleanup files
        for path in [self.config.socket_path, self.config.pid_path]:
            if os.path.exists(path):
                os.unlink(path)


def start_daemon(foreground: bool = True):
    """Start the agent daemon.

    Args:
        foreground: If True (default), run in the current process with logs
            printed to stderr. If False, double-fork into the background.
    """
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e))

    if not foreground:
        _start_background(config)
        return

    # --- Foreground mode ---
    log_dir = config.project_dir / ".ezagent"
    log_dir.mkdir(exist_ok=True)

    log_fmt = "%(asctime)s %(levelname)s %(message)s"
    file_handler = logging.FileHandler(str(log_dir / "scheduler.log"))
    file_handler.setFormatter(logging.Formatter(log_fmt))
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter(log_fmt))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stderr_handler)

    daemon = AgentDaemon(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _signal_handler():
        loop.create_task(daemon.shutdown())
        loop.stop()

    loop.add_signal_handler(signal.SIGTERM, _signal_handler)
    loop.add_signal_handler(signal.SIGINT, _signal_handler)

    try:
        loop.run_until_complete(daemon.initialize())
        loop.run_until_complete(daemon.start())
    except Exception:
        logging.exception("Daemon failed during startup")
        loop.run_until_complete(daemon.shutdown())
    finally:
        loop.close()


def _start_background(config: ProjectConfig):
    """Double-fork into the background (original daemon behaviour)."""
    pid = os.fork()
    if pid > 0:
        click.echo(f"Starting daemon (PID {pid})...")
        return

    os.setsid()

    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)

    # Redirect stdio to /dev/null
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)

    log_dir = config.project_dir / ".ezagent"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        filename=str(log_dir / "scheduler.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    daemon = AgentDaemon(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _signal_handler():
        loop.create_task(daemon.shutdown())
        loop.stop()

    loop.add_signal_handler(signal.SIGTERM, _signal_handler)
    loop.add_signal_handler(signal.SIGINT, _signal_handler)

    try:
        loop.run_until_complete(daemon.initialize())
        loop.run_until_complete(daemon.start())
    except Exception:
        logging.exception("Daemon failed during startup")
        loop.run_until_complete(daemon.shutdown())
    finally:
        loop.close()


def stop_daemon():
    """Stop the running agent daemon."""
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e))

    pid_path = config.pid_path
    if not os.path.exists(pid_path):
        raise click.ClickException("No running daemon found (PID file missing).")

    with open(pid_path) as f:
        pid = int(f.read().strip())

    try:
        os.kill(pid, signal.SIGTERM)
        click.echo(f"Sent SIGTERM to daemon (PID {pid})")
    except ProcessLookupError:
        click.echo("Daemon process not found. Cleaning up stale files.")

    # Cleanup
    for path in [config.socket_path, pid_path]:
        if os.path.exists(path):
            os.unlink(path)

    click.echo("Daemon stopped.")


def get_status() -> dict:
    """Check daemon status and return agent information."""
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e))

    result: Dict[str, Any] = {
        "running": False,
        "pid": None,
        "socket": config.socket_path,
        "project_dir": str(config.project_dir),
        "agents": {},
        "discussions": {},
    }

    # Build agent info from config (used when daemon isn't running)
    config_agents = {}
    now = datetime.now(timezone.utc)
    for name, ac in config.agents.items():
        provider_name = ac.provider or config.provider
        model = ac.model or config.model
        schedule_info = []
        for entry in ac.schedule:
            next_run = croniter(entry.cron, now).get_next(datetime)
            schedule_info.append({
                "cron": entry.cron,
                "message": entry.message,
                "next_run": next_run.isoformat(),
            })
        config_agents[name] = {
            "description": ac.description,
            "provider": provider_name,
            "model": model,
            "tools": ac.tools,
            "skills": ac.skills,
            "schedule": schedule_info,
        }

    # Build discussion info from config
    config_discussions = {}
    for name, dc in config.discussions.items():
        schedule_info = []
        for entry in dc.schedule:
            next_run = croniter(entry.cron, now).get_next(datetime)
            schedule_info.append({
                "cron": entry.cron,
                "message": entry.message,
                "next_run": next_run.isoformat(),
            })
        config_discussions[name] = {
            "participants": [p.agent for p in dc.participants],
            "termination": dc.termination,
            "max_rounds": dc.max_rounds,
            "moderator": dc.moderator,
            "schedule": schedule_info,
        }

    pid_path = config.pid_path
    if not os.path.exists(pid_path):
        result["agents"] = config_agents
        result["discussions"] = config_discussions
        return result

    with open(pid_path) as f:
        try:
            pid = int(f.read().strip())
        except ValueError:
            result["agents"] = config_agents
            return result

    # Check if process is alive
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        result["agents"] = config_agents
        return result

    result["running"] = True
    result["pid"] = pid

    # Query live agent info from daemon via socket
    sock_path = config.socket_path
    if os.path.exists(sock_path):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(sock_path)
            sock.sendall(json.dumps({"type": "status"}).encode())
            sock.shutdown(socket.SHUT_WR)

            buffer = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
            sock.close()

            for line in buffer.decode().strip().split("\n"):
                if not line:
                    continue
                resp = json.loads(line)
                if resp.get("type") == "status":
                    result["agents"] = resp.get("agents", {})
                    result["discussions"] = resp.get("discussions", {})
                    return result
        except (ConnectionRefusedError, OSError, json.JSONDecodeError):
            pass

    # Fallback to config info if socket query failed
    result["agents"] = config_agents
    result["discussions"] = config_discussions
    return result


def send_message(agent_name: str, message: str, debug: bool = False):
    """Send a message to the daemon and print the response."""
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e))

    sock_path = config.socket_path
    if not os.path.exists(sock_path):
        raise click.ClickException(
            "Daemon is not running. Start it with: ez start"
        )

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(sock_path)
    except ConnectionRefusedError:
        raise click.ClickException(
            "Cannot connect to daemon. Try restarting with: ez stop && ez start"
        )

    request = json.dumps({"agent": agent_name, "message": message, "debug": debug})
    sock.sendall(request.encode())
    sock.shutdown(socket.SHUT_WR)

    # Read newline-delimited JSON responses
    buffer = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buffer += chunk

    sock.close()

    for line in buffer.decode().strip().split("\n"):
        if not line:
            continue
        try:
            resp = json.loads(line)
            msg_type = resp.get("type")
            if msg_type == "error":
                raise click.ClickException(resp.get("text", "Unknown error"))
            if msg_type == "debug":
                click.echo(f"[debug] {resp.get('text', '')}", err=True)
            else:
                click.echo(resp.get("text", ""))
        except json.JSONDecodeError:
            click.echo(line)


def send_discussion(discussion_name: str, topic: str):
    """Send a discuss request to the daemon and print the transcript + decision."""
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e))

    sock_path = config.socket_path
    if not os.path.exists(sock_path):
        raise click.ClickException(
            "Daemon is not running. Start it with: ez start"
        )

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(sock_path)
    except ConnectionRefusedError:
        raise click.ClickException(
            "Cannot connect to daemon. Try restarting with: ez stop && ez start"
        )

    request = json.dumps({"type": "discuss", "discussion": discussion_name, "topic": topic})
    sock.sendall(request.encode())
    sock.shutdown(socket.SHUT_WR)

    buffer = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buffer += chunk
    sock.close()

    for line in buffer.decode().strip().split("\n"):
        if not line:
            continue
        try:
            resp = json.loads(line)
        except json.JSONDecodeError:
            click.echo(line)
            continue

        if "error" in resp:
            raise click.ClickException(resp["error"])

        # Print each turn grouped by round
        transcript = resp.get("transcript", [])
        current_round = 0
        for turn in transcript:
            if turn["round"] != current_round:
                current_round = turn["round"]
                click.echo(f"\n{'─' * 60}")
                click.echo(f"  Round {current_round}")
                click.echo(f"{'─' * 60}")
            click.echo(f"\n[{turn['agent'].upper()}]")
            click.echo(turn["content"])

        # Final outcome
        state = resp.get("terminal_state", "unknown").upper().replace("_", " ")
        click.echo(f"\n{'═' * 60}")
        click.echo(f"  OUTCOME: {state}  (after {resp.get('rounds_completed', '?')} round(s))")
        click.echo(f"{'═' * 60}")
        click.echo(f"\n{resp.get('decision', '')}")
        if resp.get("dissent"):
            click.echo(f"\nDISSENT: {resp['dissent']}")

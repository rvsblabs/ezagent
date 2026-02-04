from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import click
from croniter import croniter

from ezagent.agent import Agent, AgentResult
from ezagent.config import ProjectConfig, load_config
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
            )
            await agent.initialize()
            self.agents[name] = agent

        self._build_schedule()

    def _build_schedule(self):
        """Build the list of scheduled entries from agent configs."""
        now = datetime.now(timezone.utc)
        for name, agent_config in self.config.agents.items():
            for entry in agent_config.schedule:
                cron_iter = croniter(entry.cron, now)
                next_run = cron_iter.get_next(datetime)
                self._schedule_entries.append({
                    "agent_name": name,
                    "cron_expr": entry.cron,
                    "message": entry.message,
                    "cron_iter": cron_iter,
                    "next_run": next_run,
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
                            "Firing scheduled run: agent=%s cron=%r",
                            entry["agent_name"],
                            entry["cron_expr"],
                        )
                        asyncio.create_task(
                            self._execute_scheduled_run(
                                entry["agent_name"],
                                entry["message"],
                                entry["cron_expr"],
                            )
                        )
                        entry["next_run"] = entry["cron_iter"].get_next(datetime)
        except asyncio.CancelledError:
            logging.info("Scheduler loop cancelled")

    async def _execute_scheduled_run(
        self, agent_name: str, message: str, cron_expr: str
    ):
        """Execute a single scheduled agent run."""
        agent = self.agents.get(agent_name)
        if agent is None:
            logging.error("Scheduled run: agent %r not found", agent_name)
            return
        try:
            result = await agent.run(message)
            logging.info(
                "Scheduled run completed: agent=%s cron=%r result_length=%d",
                agent_name,
                cron_expr,
                len(result.text),
            )
        except Exception:
            logging.exception(
                "Scheduled run failed: agent=%s cron=%r", agent_name, cron_expr
            )

    async def _delegate_to_agent(
        self, agent_name: str, message: str, depth: int, debug: bool = False
    ) -> AgentResult:
        """Callback for agent-as-tool delegation."""
        agent = self.agents.get(agent_name)
        if agent is None:
            return AgentResult(text=json.dumps({"error": f"Agent '{agent_name}' not found"}))
        return await agent.run(message, depth=depth, debug=debug)

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
                    schedule_info = []
                    for entry in self._schedule_entries:
                        if entry["agent_name"] == name:
                            schedule_info.append({
                                "cron": entry["cron_expr"],
                                "message": entry["message"],
                                "next_run": entry["next_run"].isoformat(),
                            })
                    agents_info[name] = {
                        "description": ac.description,
                        "provider": provider_name,
                        "model": model,
                        "tools": ac.tools,
                        "skills": ac.skills,
                        "schedule": schedule_info,
                    }
                response = {"type": "status", "agents": agents_info}
                writer.write((json.dumps(response) + "\n").encode())
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


def start_daemon():
    """Start the agent daemon in a background process."""
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e))

    # Fork into background
    pid = os.fork()
    if pid > 0:
        # Parent process — wait briefly then check child is alive
        click.echo(f"Starting daemon (PID {pid})...")
        return

    # Child process — detach
    os.setsid()

    # Second fork to fully daemonize
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)

    # Redirect stdio to /dev/null
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)

    # Set up logging for scheduler
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

    pid_path = config.pid_path
    if not os.path.exists(pid_path):
        result["agents"] = config_agents
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
                    return result
        except (ConnectionRefusedError, OSError, json.JSONDecodeError):
            pass

    # Fallback to config agents if socket query failed
    result["agents"] = config_agents
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

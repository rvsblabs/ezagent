from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import sys
from pathlib import Path
from typing import Dict

import click

from ezagent.agent import Agent, AgentResult
from ezagent.config import ProjectConfig, load_config
from ezagent.llm.anthropic import AnthropicProvider


class AgentDaemon:
    """Background daemon that hosts agents and listens on a Unix socket."""

    def __init__(self, config: ProjectConfig):
        self.config = config
        self.agents: Dict[str, Agent] = {}
        self._server: asyncio.AbstractServer | None = None

    async def initialize(self):
        """Create and initialize all agents."""
        provider = AnthropicProvider()
        agent_names = list(self.config.agents.keys())

        for name, agent_config in self.config.agents.items():
            agent = Agent(
                name=name,
                config=agent_config,
                project_dir=self.config.project_dir,
                provider=provider,
                agent_names=agent_names,
                agent_runner=self._delegate_to_agent,
            )
            await agent.initialize()
            self.agents[name] = agent

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

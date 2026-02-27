from __future__ import annotations

from pathlib import Path

import click

from ezagent.config import find_project_dir
from ezagent.scaffold import (
    DOCKERFILE,
    DOCKER_COMPOSE,
    DOCKERIGNORE,
    ENV_EXAMPLE,
    PROJECT_CLAUDE_MD,
    create_project,
    create_skill,
    create_tool,
)


class EzGroup(click.Group):
    """Custom Click group that routes unknown commands to 'run'.

    This allows `ez <agent_name> <message>` to work as a shorthand
    for `ez run <agent_name> <message>`.
    """

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        # Try built-in commands first
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv
        # Treat unknown command as agent name -> delegate to run
        return super().get_command(ctx, "run")

    def resolve_command(self, ctx: click.Context, args: list[str]) -> tuple:
        cmd_name, cmd, cmd_args = super().resolve_command(ctx, args)
        if cmd is None and args:
            # Fallback: rewrite as `run <agent_name> <rest...>`
            cmd = super().get_command(ctx, "run")
            cmd_name = "run"
            cmd_args = args
        return cmd_name, cmd, cmd_args

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        # Find the first non-option arg and check if it's a known command.
        # If not, insert 'run' before it so `ez --debug myagent "msg"` works.
        for i, arg in enumerate(args):
            if not arg.startswith("-"):
                if arg not in self.commands:
                    args = args[:i] + ["run"] + args[i:]
                break
        return super().parse_args(ctx, args)


@click.group(cls=EzGroup)
@click.version_option(package_name="ezagent")
@click.option("--debug", is_flag=True, default=False, help="Show debug output (LLM calls, tool calls, skill loading).")
@click.pass_context
def cli(ctx: click.Context, debug: bool):
    """ez — low-code AI agent CLI"""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug


@cli.command()
@click.argument("app_name")
def init(app_name: str):
    """Initialize a new ezagent project."""
    try:
        path = create_project(app_name)
        click.echo(f"Created project at {path}")
        click.echo(f"  {app_name}/pyproject.toml      — Python project + dependencies")
        click.echo(f"  {app_name}/agents.yml          — configure your agents")
        click.echo(f"  {app_name}/tools/              — add FastMCP tool servers here")
        click.echo(f"  {app_name}/skills/             — add skill .md files here")
        click.echo(f"  {app_name}/CLAUDE.md           — Claude Code project guide")
        click.echo(f"  {app_name}/Dockerfile          — container image definition")
        click.echo(f"  {app_name}/docker-compose.yml  — containerized dev (daemon + api)")
        click.echo(f"  {app_name}/.env.example        — copy to .env and fill in API keys")
        click.echo("")
        click.echo("Next steps:")
        click.echo(f"  cd {app_name}")
        click.echo(f"  cp .env.example .env  # add your API keys")
        click.echo(f"  uv sync               # install dependencies")
        click.echo(f"  uv run ez start       # start the daemon")
    except FileExistsError as e:
        raise click.ClickException(str(e))


@cli.group()
def create():
    """Scaffold new tools or skills."""


@create.command("tool")
@click.argument("name")
def create_tool_cmd(name: str):
    """Create a new tool scaffold: <name>/main.py + requirements.txt"""
    project_dir = find_project_dir()
    if project_dir is not None:
        base_dir = project_dir / "tools"
    else:
        base_dir = Path.cwd()
    try:
        path = create_tool(name, base_dir)
        click.echo(f"Created tool at {path}")
        click.echo(f"  {path}/main.py         — implement your FastMCP tool here")
        click.echo(f"  {path}/requirements.txt — add dependencies if needed")
        if project_dir is not None:
            click.echo(f"\nNext: add '{name}' to an agent's tools list in agents.yml")
    except FileExistsError as e:
        raise click.ClickException(str(e))


@create.command("skill")
@click.argument("name")
def create_skill_cmd(name: str):
    """Create a new skill scaffold: <name>.md"""
    project_dir = find_project_dir()
    if project_dir is not None:
        base_dir = project_dir / "skills"
    else:
        base_dir = Path.cwd()
    try:
        path = create_skill(name, base_dir)
        click.echo(f"Created skill at {path}")
        if project_dir is not None:
            click.echo(f"\nNext: add '{name}' to an agent's skills list in agents.yml")
    except FileExistsError as e:
        raise click.ClickException(str(e))


@cli.command("update-docs")
def update_docs():
    """Regenerate CLAUDE.md and add any missing Docker scaffold files."""
    project_dir = find_project_dir()
    if project_dir is None:
        raise click.ClickException(
            "No agents.yml found. Run this from inside an ezagent project."
        )

    # CLAUDE.md — always overwrite (generated template, not user-customised)
    claude_md = project_dir / "CLAUDE.md"
    existed = claude_md.exists()
    claude_md.write_text(PROJECT_CLAUDE_MD)
    if existed:
        click.echo(f"Updated {claude_md} with the latest ezagent template.")
    else:
        click.echo(f"Created {claude_md}")

    # Docker scaffold files — create only if missing (user may have customised them)
    docker_files = [
        ("Dockerfile", DOCKERFILE),
        ("docker-compose.yml", DOCKER_COMPOSE),
        (".dockerignore", DOCKERIGNORE),
        (".env.example", ENV_EXAMPLE),
    ]
    for filename, template in docker_files:
        path = project_dir / filename
        if path.exists():
            click.echo(f"  {filename} already exists, skipping.")
        else:
            path.write_text(template)
            click.echo(f"  Created {filename}")


@cli.command()
def tools():
    """List available tools (prebuilt and project-local)."""
    from ezagent.tools.builtins import PREBUILT_TOOLS

    click.echo("Prebuilt tools (available to any project):")
    for name, path in PREBUILT_TOOLS.items():
        # Read the tool's main.py docstring for a description
        main_py = path / "main.py"
        desc = ""
        if main_py.is_file():
            import ast

            try:
                tree = ast.parse(main_py.read_text())
                desc = ast.get_docstring(tree) or ""
                # Use only the first line
                desc = desc.split("\n")[0]
            except Exception:
                pass
        click.echo(f"  {name:<16} {desc}")

    project_dir = find_project_dir()
    if project_dir is not None:
        tools_dir = project_dir / "tools"
        if tools_dir.is_dir():
            local_tools = sorted(
                d.name for d in tools_dir.iterdir()
                if d.is_dir() and (d / "main.py").is_file()
            )
            if local_tools:
                click.echo(f"\nProject tools ({project_dir.name}/tools/):")
                for name in local_tools:
                    click.echo(f"  {name}")
            else:
                click.echo("\nNo project tools found.")
    else:
        click.echo("\nNo project directory found (not inside an ezagent project).")


@cli.command()
@click.option("--daemon", "-d", is_flag=True, default=False, help="Run in background (daemonize).")
def start(daemon: bool):
    """Start the agent daemon."""
    from ezagent.daemon import start_daemon

    start_daemon(foreground=not daemon)


@cli.command()
def stop():
    """Stop the agent daemon."""
    from ezagent.daemon import stop_daemon

    stop_daemon()


@cli.command()
def status():
    """Show daemon status and configured agents."""
    from ezagent.daemon import get_status

    info = get_status()

    if info["running"]:
        click.echo(f"Daemon: running (PID {info['pid']})")
        click.echo(f"Socket: {info['socket']}")
    else:
        click.echo("Daemon: not running")

    click.echo(f"Project: {info['project_dir']}")

    agents = info.get("agents", {})
    if not agents:
        click.echo("\nNo agents configured.")
    else:
        if info["running"]:
            click.echo("\nAgents:")
        else:
            click.echo("\nConfigured agents (from agents.yml):")
        for name, details in agents.items():
            provider = details.get("provider", "")
            model = details.get("model", "")
            provider_model = f"{provider}/{model}" if model else provider
            tools = ", ".join(details.get("tools", [])) or "\u2014"
            skills = ", ".join(details.get("skills", [])) or "\u2014"
            click.echo(f"  {name:<16} {provider_model:<32} tools: {tools:<24} skills: {skills}")
            for sched in details.get("schedule", []):
                cron = sched.get("cron", "")
                next_run = sched.get("next_run", "")
                msg = sched.get("message", "")
                click.echo(f"    schedule: {cron:<20} next: {next_run:<26} \"{msg}\"")

    discussions = info.get("discussions", {})
    if discussions:
        click.echo("\nDiscussions:")
        for name, details in discussions.items():
            participants = ", ".join(details.get("participants", [])) or "\u2014"
            termination = details.get("termination", "rounds")
            max_rounds = details.get("max_rounds", 5)
            click.echo(
                f"  {name:<16} participants: {participants:<32} "
                f"termination: {termination} max_rounds: {max_rounds}"
            )
            for sched in details.get("schedule", []):
                cron = sched.get("cron", "")
                next_run = sched.get("next_run", "")
                msg = sched.get("message", "")
                click.echo(f"    schedule: {cron:<20} next: {next_run:<26} \"{msg}\"")

    orchestrations = info.get("orchestrations", {})
    if orchestrations:
        click.echo("\nOrchestrations:")
        for name, details in orchestrations.items():
            pattern = details.get("pattern", "plan_and_delegate")
            planner = details.get("planner", "")
            workers = ", ".join(details.get("workers", [])) or "\u2014"
            click.echo(
                f"  {name:<16} pattern: {pattern:<20} planner: {planner:<12} workers: {workers}"
            )


@cli.command()
@click.argument("agent_name")
@click.argument("message", nargs=-1, required=True)
@click.pass_context
def run(ctx: click.Context, agent_name: str, message: tuple[str, ...]):
    """Send a message to an agent. Usage: ez run <agent> <message>"""
    from ezagent.daemon import send_message

    debug = ctx.obj.get("debug", False)
    full_message = " ".join(message)
    send_message(agent_name, full_message, debug=debug)


@cli.command("discuss")
@click.argument("discussion_name")
@click.argument("topic", nargs=-1, required=True)
def discuss(discussion_name: str, topic: tuple[str, ...]):
    """Run a multi-agent discussion. Usage: ez discuss <discussion> <topic>"""
    from ezagent.daemon import send_discussion

    send_discussion(discussion_name, " ".join(topic))


@cli.command("orchestrate")
@click.argument("orchestration_name")
@click.argument("message", nargs=-1, required=True)
def orchestrate(orchestration_name: str, message: tuple[str, ...]):
    """Run an orchestration (plan-and-delegate). Usage: ez orchestrate <name> <message>"""
    from ezagent.daemon import send_orchestration

    send_orchestration(orchestration_name, " ".join(message))


@cli.command("serve")
@click.option("--port", default=7771, show_default=True, help="Port to listen on.")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind to.")
def serve(port: int, host: str):
    """Start the HTTP + WebSocket API server."""
    try:
        import uvicorn
        from ezagent.server import create_app
    except ImportError:
        raise click.ClickException(
            "Install with: uv sync --extra serve  (or pip install 'ezagent[serve]')"
        )
    from ezagent.config import load_config
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e))
    app = create_app(config)
    click.echo(f"ez serve → http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


@cli.command("logs")
@click.option("--agent", default=None, help="Filter by agent name.")
@click.option("--orchestration", default=None, help="Filter by orchestration name.")
@click.option("--limit", default=20, show_default=True, help="Number of rows to show.")
@click.option(
    "--status",
    default=None,
    type=click.Choice(["running", "success", "error"]),
    help="Filter by run status.",
)
def logs(agent: str | None, orchestration: str | None, limit: int, status: str | None):
    """Show recent agent run logs."""
    import sqlite3
    import datetime as dt

    project_dir = find_project_dir()
    if project_dir is None:
        raise click.ClickException(
            "No agents.yml found. Run this from inside an ezagent project."
        )

    db_path = project_dir / ".ezagent" / "events.db"
    if not db_path.exists():
        click.echo("No event log found. Run an agent first.")
        return

    if orchestration:
        rows = _read_orchestration_logs(db_path, orchestration=orchestration, limit=limit)
        if not rows:
            click.echo("No orchestration logs found.")
            return
        header = f"{'ORCHESTRATION':<18} {'STATUS':<10} {'INPUT':<42} {'DURATION':>10}  STARTED"
        click.echo(header)
        click.echo("-" * len(header))
        for row in rows:
            orch_name, row_status, input_msg, duration_ms, started_at = row
            input_str = (input_msg or "")
            input_trunc = input_str[:40] + ("..." if len(input_str) > 40 else "")
            duration_str = f"{duration_ms}ms" if duration_ms is not None else "running"
            started_str = (
                dt.datetime.fromtimestamp(started_at).strftime("%Y-%m-%d %H:%M:%S")
                if started_at
                else ""
            )
            click.echo(
                f"{(orch_name or ''):<18} {(row_status or ''):<10} "
                f"{input_trunc:<42} {duration_str:>10}  {started_str}"
            )
    else:
        rows = _read_logs(db_path, agent=agent, limit=limit, status=status)
        if not rows:
            click.echo("No logs found.")
            return
        header = f"{'AGENT':<16} {'SOURCE':<12} {'STATUS':<10} {'INPUT':<42} {'DURATION':>10}  STARTED"
        click.echo(header)
        click.echo("-" * len(header))
        for row in rows:
            agent_name, source, row_status, input_msg, duration_ms, started_at = row
            input_str = (input_msg or "")
            input_trunc = input_str[:40] + ("..." if len(input_str) > 40 else "")
            duration_str = f"{duration_ms}ms" if duration_ms is not None else "running"
            started_str = (
                dt.datetime.fromtimestamp(started_at).strftime("%Y-%m-%d %H:%M:%S")
                if started_at
                else ""
            )
            click.echo(
                f"{(agent_name or ''):<16} {(source or ''):<12} {(row_status or ''):<10} "
                f"{input_trunc:<42} {duration_str:>10}  {started_str}"
            )


def _read_logs(
    db_path: Path,
    agent: str | None = None,
    limit: int = 20,
    status: str | None = None,
) -> list:
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        query = (
            "SELECT agent_name, source, status, input_message, duration_ms, started_at "
            "FROM agent_runs"
        )
        conditions = []
        params: list = []
        if agent:
            conditions.append("agent_name = ?")
            params.append(agent)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def _read_orchestration_logs(
    db_path: Path,
    orchestration: str | None = None,
    limit: int = 20,
) -> list:
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        query = (
            "SELECT orchestration_name, status, message, duration_ms, started_at "
            "FROM orchestration_runs"
        )
        params: list = []
        if orchestration:
            query += " WHERE orchestration_name = ?"
            params.append(orchestration)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()

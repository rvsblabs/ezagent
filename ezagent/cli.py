from __future__ import annotations

from pathlib import Path

import click

from ezagent.config import find_project_dir
from ezagent.scaffold import create_project, create_skill, create_tool


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
        click.echo(f"  {app_name}/tools/     — add FastMCP tool servers here")
        click.echo(f"  {app_name}/skills/    — add skill .md files here")
        click.echo(f"  {app_name}/agents.yml — configure your agents")
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


@cli.command()
def start():
    """Start the agent daemon."""
    from ezagent.daemon import start_daemon

    start_daemon()


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

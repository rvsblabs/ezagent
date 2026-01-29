from __future__ import annotations

import click

from ezagent.scaffold import create_project


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
@click.argument("agent_name")
@click.argument("message", nargs=-1, required=True)
@click.pass_context
def run(ctx: click.Context, agent_name: str, message: tuple[str, ...]):
    """Send a message to an agent. Usage: ez run <agent> <message>"""
    from ezagent.daemon import send_message

    debug = ctx.obj.get("debug", False)
    full_message = " ".join(message)
    send_message(agent_name, full_message, debug=debug)

# Development Guide

How to set up, test, and debug ezagent locally.

## Setup

```bash
git clone https://github.com/rvsblabs/ezagent.git
cd ezagent
uv sync
```

This creates a `.venv` and installs all dependencies including `ezagent` itself in editable mode.

Run any `ez` command through uv:

```bash
uv run ez --version
```

## Testing Locally

### Step 1 — Scaffold a test project

```bash
uv run ez init testproject
cd testproject
```

This creates a ready-to-run project with a sample tool and skill:

```text
testproject/
  tools/
    greeter/
      main.py          # Sample FastMCP tool that greets by name
  skills/
    friendly.md        # Sample skill prompt
  agents.yml           # Pre-wired assistant agent
```

The generated `agents.yml` comes pre-configured:

```yaml
agents:
  assistant:
    tools: greeter
    skills: friendly
    description: "A friendly assistant that can greet people by name"
```

### Step 2 — Set your API key and start the daemon

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run ez start
```

Verify it's running:

```bash
uv run ez status
```

### Step 3 — Send a message

```bash
uv run ez assistant "Hi, my name is Alice"
```

The agent should use the `greeter` tool to greet Alice. You can also use the explicit form:

```bash
uv run ez run assistant "Hi, my name is Alice"
```

### Step 4 — Stop the daemon

```bash
uv run ez stop
```

## Adding Your Own Tools and Skills

The scaffolded project comes with a sample `greeter` tool and `friendly` skill. To add more:

### Add a tool

Create `tools/<tool_name>/main.py` with a FastMCP server:

```python
from fastmcp import FastMCP

mcp = FastMCP("my_tool")


@mcp.tool()
def my_function(arg: str) -> str:
    """Describe what this tool does."""
    return f"Result: {arg}"


if __name__ == "__main__":
    mcp.run()
```

### Add tool dependencies

If your tool needs external packages, add a `requirements.txt` alongside `main.py`:

```text
tools/my_tool/
  main.py
  requirements.txt    # one requirement per line, e.g. "requests>=2.28"
```

Or use a `pyproject.toml` for full project-style dependency management. When either file is present, ezagent automatically uses `uv` to run the tool with those dependencies available.

### Add a skill

Skills are loaded dynamically: the system prompt only includes skill names and one-line summaries (extracted from the first non-empty line of the markdown file). The agent calls the `use_skill` tool to load full instructions on demand, keeping the context window lean when many skills are assigned.

Create `skills/<skill_name>.md` with instructions for the agent:

```markdown
You are an expert at X. When asked to do Y, follow these steps:
1. First step
2. Second step
```

### Wire them in agents.yml

```yaml
agents:
  assistant:
    tools: greeter, my_tool
    skills: friendly, my_skill
    description: "An assistant with multiple tools and skills"
```

## Testing the Prebuilt Memory Tool

Add `memory` to an agent's tools in `agents.yml`:

```yaml
agents:
  assistant:
    tools: greeter, memory
    skills: friendly
    description: "A friendly assistant with persistent memory"
```

Then test the four memory operations:

```bash
uv run ez start

# Store a memory
uv run ez assistant "Remember that my favorite color is blue"

# Search memories
uv run ez assistant "What is my favorite color?"

# List all memories
uv run ez assistant "List all my memories"

# Delete a memory (use an ID returned from list/store)
uv run ez assistant "Delete memory <id>"

uv run ez stop
```

Memories persist in `.ezagent/memory/milvus.db` inside the project directory. The embedding model (`all-MiniLM-L6-v2`, ~90MB) downloads on first use. All dependencies (`pymilvus`, `sentence-transformers`) are installed automatically by `uv` in an isolated environment.

## Testing Cron Scheduling

Add a `schedule` to an agent in `agents.yml`. Use `* * * * *` (every minute) for quick testing:

```yaml
agents:
  assistant:
    tools: greeter
    skills: friendly
    description: "A friendly assistant that can greet people by name"
    schedule:
      - cron: "* * * * *"
        message: "Say hello to the world"
```

### Verify config parsing (no daemon needed)

```bash
uv run ez status
```

You should see the schedule line printed below the agent with the cron expression, next run time, and message.

### Run with the daemon

```bash
uv run ez start
uv run ez status          # shows live next_run times from the daemon
cat .ezagent/scheduler.log  # "Scheduler initialized", "Scheduler loop started"
```

Within a minute you'll see `Firing scheduled run` and `Scheduled run completed` (or `failed` if there's no API key) in the log.

### Verify cron validation

Invalid cron expressions are rejected at config load time:

```bash
uv run python -c "from ezagent.config import ScheduleEntry; ScheduleEntry(cron='bad', message='x')"
# raises ValidationError
```

### Clean shutdown

```bash
uv run ez stop
cat .ezagent/scheduler.log  # should show "Scheduler loop cancelled"
```

Agents without a `schedule` key are unaffected — they work exactly as before.

## Testing the Web Search Tool

Add `web_search` to an agent's tools in `agents.yml`:

```yaml
agents:
  researcher:
    tools: web_search
    description: "An agent that can search the web"
```

Set the Brave Search API key and test:

```bash
export BRAVE_SEARCH_API_KEY=your-key-here

uv run ez start

# Search the web
uv run ez researcher "Search for the latest Python 3.13 features"

# The agent can also read full page content from search results
uv run ez researcher "Find and read the Python 3.13 release notes"

uv run ez stop
```

Get a free API key at [brave.com/search/api](https://brave.com/search/api/).

### Missing API key

If `BRAVE_SEARCH_API_KEY` is not set, the tool returns an error message explaining how to get a key.

### Verify registration

```bash
uv run python -c "from ezagent.tools.builtins import PREBUILT_TOOLS; print(PREBUILT_TOOLS)"
```

You should see `web_search` in the output dictionary.

## Testing the HTTP Tool

Add `http` to an agent's tools in `agents.yml`:

```yaml
agents:
  assistant:
    tools: http
    description: "An agent that can make HTTP requests"
```

Then test with public APIs (no auth needed):

```bash
uv run ez start

# Make a GET request
uv run ez assistant "Make a GET request to https://httpbin.org/get and tell me my IP"

# POST JSON data
uv run ez assistant "POST {'name': 'test'} to https://httpbin.org/post and show the response"

# Read a web page
uv run ez assistant "Read the content of https://example.com"

uv run ez stop
```

### Verify registration

```bash
uv run python -c "from ezagent.tools.builtins import PREBUILT_TOOLS; print(PREBUILT_TOOLS)"
```

You should see `http` in the output dictionary.

## Testing the Filesystem Tool

Add `filesystem` to an agent's tools in `agents.yml`:

```yaml
agents:
  assistant:
    tools: filesystem
    skills: friendly
    description: "A friendly assistant that can read and write files"
```

Then test the four operations:

```bash
uv run ez start

# Create a directory
uv run ez assistant "Create a directory called test_output"

# Write a file
uv run ez assistant "Write 'hello world' to test_output/hello.txt"

# Read a file
uv run ez assistant "Read the file test_output/hello.txt"

# List directory contents
uv run ez assistant "List the contents of the test_output directory"

uv run ez stop
```

No API keys or external dependencies are needed — the filesystem tool uses Python stdlib only.

### Verify registration

```bash
uv run python -c "from ezagent.tools.builtins import PREBUILT_TOOLS; print(PREBUILT_TOOLS)"
```

You should see `filesystem` in the output dictionary.

## Testing Agent-as-Tool Delegation

Update `agents.yml` to have two agents where one delegates to the other:

```yaml
agents:
  manager:
    tools: worker
    skills:
    description: "A manager that delegates research tasks"

  worker:
    tools:
    skills:
    description: "A worker that handles delegated tasks"
```

```bash
uv run ez start
uv run ez manager "Explain what a Unix socket is"
uv run ez stop
```

The `manager` agent will see `worker` as a callable tool and can delegate to it.

## Debugging

### Debug mode

Use the `--debug` flag to see skill loading, LLM calls, tool calls, and agent delegation in real time. Debug output is printed to stderr so it doesn't interfere with the agent's response on stdout.

```bash
uv run ez --debug assistant "Hi, my name is Alice"
```

Example output:

```
[debug] [assistant] Skills available: friendly
[debug] [assistant] Calling LLM...
[debug] [assistant] Tool call: greeter__greet({"name": "Alice"})
[debug] [assistant] Tool result: Hello, Alice! Welcome to ezagent.
[debug] [assistant] Calling LLM...
I greeted Alice for you!
```

The `--debug` flag is a top-level option that works with both explicit and shorthand forms:

```bash
# Shorthand
uv run ez --debug assistant "Hi"

# Explicit
uv run ez --debug run assistant "Hi"
```

### Check if daemon is running

```bash
uv run ez status
```

### Daemon won't start

If the daemon fails to start (e.g. stale socket from a crash):

```bash
# Clean up manually
rm /tmp/ezagent_*.sock /tmp/ezagent_*.pid

# Try again
uv run ez start
```

### Common errors

| Error | Cause | Fix |
| ----- | ----- | --- |
| `ANTHROPIC_API_KEY environment variable is not set` | Missing API key | `export ANTHROPIC_API_KEY=sk-ant-...` |
| `No agents.yml found` | Not in a project directory | `cd` into a directory with `agents.yml` |
| `Daemon is not running` | Daemon not started or crashed | Run `uv run ez start` |
| `daemon already running` | Previous daemon still active | Run `uv run ez stop` first |
| `skill file not found` | Skill listed in YAML but `.md` file missing | Create the file in `skills/` |
| `tool ... is neither an agent nor a tool directory` | Tool listed in YAML but no `main.py` | Create `tools/<name>/main.py` |
| `Invalid cron expression` | Bad cron syntax in `schedule` | Fix the `cron` value in `agents.yml` |
| `429` / rate-limit errors from Anthropic | Too many API calls in quick succession | The agentic loop includes a 1-second delay between tool-loop iterations to mitigate this automatically |

### Run CLI directly without install

For quick iteration you can also invoke the module directly:

```bash
uv run python -m ezagent.cli --help
```

This requires adding a `__main__.py`. Alternatively, `uv sync` already installs the package in editable mode, so code changes are picked up immediately — just re-run `uv run ez ...`.

## Project Structure

```text
ezagent/
  __init__.py          # Package version
  cli.py               # Click CLI entry point (init, start, stop, status, run)
  config.py            # Pydantic models, YAML loading, validation
  scaffold.py          # ez init scaffolding
  agent.py             # Agent class with agentic tool-use loop (includes rate-limit delay between iterations)
  daemon.py            # Background daemon, Unix socket server, cron scheduler, PID management
  llm/
    base.py            # Abstract LLMProvider interface
    anthropic.py       # Anthropic implementation
  tools/
    manager.py         # FastMCP client lifecycle, schema conversion, dispatch
    builtins/
      __init__.py      # Prebuilt tool registry (PREBUILT_TOOLS dict)
      memory/
        __init__.py    # Package marker
        main.py        # FastMCP server: store, search, delete, list
        requirements.txt  # pymilvus, sentence-transformers
      web_search/
        __init__.py    # Package marker
        main.py        # FastMCP server: web_search, web_search_read
        requirements.txt  # requests
      http/
        __init__.py    # Package marker
        main.py        # FastMCP server: http_request, http_read
        requirements.txt  # requests
      filesystem/
        __init__.py    # Package marker
        main.py        # FastMCP server: read_file, write_file, list_directory, create_directory
```

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

This runs in the foreground — logs are printed to the terminal and Ctrl+C stops it.
Use `uv run ez start -d` to run in the background instead.

Verify it's running (in another terminal, or after starting with `-d`):

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

### Using Perplexity as search provider

To use Perplexity instead of Brave:

```bash
export WEB_SEARCH_PROVIDER=perplexity
export PERPLEXITY_API_KEY=your-key-here

uv run ez start
uv run ez researcher "Search for the latest Python 3.13 features"
uv run ez stop
```

Get an API key at [docs.perplexity.ai](https://docs.perplexity.ai/).

### Missing API key

If `BRAVE_SEARCH_API_KEY` (Brave) or `PERPLEXITY_API_KEY` (Perplexity) is not set, the tool returns an error message explaining how to get a key.

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
  agent.py             # Agent class with agentic tool-use loop
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

## Perplexity Integration Design

Perplexity can integrate into ezagent in several roles:

1. **Search provider** — Perplexity as the backend for the `web_search` builtin ✅ Implemented
2. **Responses API as tools** — `perplexity_research` calls `/v1/responses` with presets ✅ Implemented
3. **Structured output API** — `extract_structured` tool for JSON-schema extraction ✅ Implemented
4. **LLM provider** — Perplexity Sonar models for the agentic chat/tool-use loop

### 1. Perplexity as Search Provider

The `web_search` builtin uses a pluggable `SearchProvider` abstraction (Brave is the default).

**Option A: Perplexity Search API**

- Perplexity has a standalone **Search API** (`POST https://api.perplexity.ai/search`) that returns raw ranked web results.
- Implement `PerplexitySearchProvider` implementing `SearchProvider.search(query, count)`.
- Map Perplexity response (`ApiSearchPage` objects with title, url, snippet) to the existing `{title, url, snippet}` format.
- Env: `WEB_SEARCH_PROVIDER=perplexity` and `PERPLEXITY_API_KEY`.

**Option B: Omit web_search when using Perplexity LLM**

- When `provider: perplexity`, Sonar models have **built-in grounded search**. The model searches internally when it needs current info.
- Agents using Perplexity as LLM may not need the `web_search` tool at all.
- Tradeoff: You lose explicit tool calls for search; behavior is opaque vs. explicit `web_search` calls.

**Recommendation:** Implement Option A for consistency and flexibility. Users can choose Perplexity as search even when using a different LLM.

---

### 2. Perplexity as LLM Provider

Add `PerplexityProvider` to `ezagent/llm/` following the existing `LLMProvider` interface.

**API details:**
- **Sonar API** (`/chat/completions`, OpenAI-compatible): Models `sonar`, `sonar-pro`, etc. Built-in search via `search_mode`. Does NOT accept custom tools — only Perplexity's built-in web_search/fetch_url.
- **Agent API** (`/v1/responses`): Supports custom tools. Different request format (`input`, `instructions`). Verify if it returns tool_calls for us to execute or runs tools server-side.

**Tool calling:** The Sonar chat completions API must support tools for the agent loop. Verify Perplexity supports OpenAI-style `tools` and `tool_calls` in chat completions. If not, Perplexity would only support “no-tools” mode (single-turn grounded answers).

**Config:**
```yaml
provider: perplexity
model: sonar-pro
```

**Implementation steps:**
1. Add `ezagent/llm/perplexity.py` implementing `LLMProvider.chat()`.
2. Use `openai` client with `base_url="https://api.perplexity.ai"` (or Perplexity Python SDK).
3. Register in `create_provider()` in `llm/__init__.py`.
4. Add `perplexity` to provider validation in config.
5. Env: `PERPLEXITY_API_KEY`.

**Note:** Sonar API does NOT support custom tools. Agent API (`POST /v1/responses`) does, but uses a different request format. Verify whether Agent API returns tool_calls for us to execute before investing in full integration.

---

### 3. Perplexity as Structured Output API

ezagent’s agent loop currently returns free-form text and tool calls; there is no native “extraction” or “structured output” path.

**Perplexity structured output:**
- `response_format: { type: "json_schema", json_schema: { schema: {...} } }` for JSON extraction.
- Optional `{ type: "regex", regex: { regex: "..." } }` for `sonar` model.

**Design options:**

**Option A: New “extraction” skill/tool**

- Add a skill or tool that, when invoked, calls Perplexity with a JSON schema to extract structured data from text.
- Use case: “Extract entities from this document” → Perplexity returns JSON matching the schema.

**Option B: Extraction-as-a-tool**

- New builtin tool `extract_structured` that takes `(text, json_schema)` and calls Perplexity’s structured output API.
- Agent can call it like any other tool when it needs structured extraction.

**Option C: Per-agent “extraction mode”**

- Extend `AgentConfig` with `extraction_provider: perplexity` and `extraction_schema: {...}`.
- When extraction is requested, the agent uses Perplexity for that step instead of the main LLM.

**Caveats:**
- First request with a new schema can be slow (10–30s) due to schema preparation.
- `sonar-reasoning-pro` emits reasoning before JSON; you may need a parser to extract the JSON.

**Recommendation:** Option B implemented — `extract_structured` builtin tool.

### 4. Perplexity Responses API as Tools (Implemented)

The `perplexity_research` prebuilt tool calls `POST /v1/responses` with presets:
- `fast-search` — Quick answers (~1 step)
- `pro-search` — Balanced research (~3 steps)
- `deep-research` — In-depth analysis (~10 steps)
- `advanced-deep-research` — Institutional-grade research

Agents add `perplexity_research` to their tools list and call it when they need AI-synthesized research rather than raw search results.

---

### Implementation Order

| Phase | Work | Status |
|-------|------|--------|
| 1 | Perplexity Search provider | ✅ Done (Option A) |
| 2 | Perplexity Responses as tools | ✅ Done (`perplexity_research`) |
| 3 | Structured output tool | ✅ Done (`extract_structured`) |
| 4 | Perplexity LLM provider | Pending; verify tool-calling support in Sonar API |

### Env Vars Summary

| Role | Env Var |
|------|---------|
| Search | `PERPLEXITY_API_KEY`, `WEB_SEARCH_PROVIDER=perplexity` |
| perplexity_research, extract_structured | `PERPLEXITY_API_KEY` |
| LLM (future) | `PERPLEXITY_API_KEY` |

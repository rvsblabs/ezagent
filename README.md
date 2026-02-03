# ezagent

Low-code CLI SDK for creating AI agents using LLMs (Anthropic, Google Gemini) and FastMCP tools.

Define agents, tools, and skills in a simple YAML config — then interact with them from any terminal.

## Installation

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install git+https://github.com/rvsblabs/ezagent.git
```

This installs the `ez` command globally.

To uninstall:

```bash
uv tool uninstall ezagent
```

### Development

To work on ezagent itself, clone the repo and sync dependencies:

```bash
git clone https://github.com/rvsblabs/ezagent.git
cd ezagent
uv sync
```

## Quick Start

### 1. Create a project

```bash
ez init myproject
cd myproject
```

This creates:

```text
myproject/
  tools/        # FastMCP tool servers
  skills/       # Skill markdown files
  agents.yml    # Agent configuration
```

### 2. Configure agents

Edit `agents.yml`:

```yaml
agents:
  researcher:
    tools: web_search, summarizer
    skills: research, write_concise
    description: "An agent that researches topics and provides concise summaries"

  summarizer:
    tools: pdf_reader
    skills: summarize
    description: "An agent that summarizes documents"
```

Agents can reference other agents as tools — `researcher` above can delegate work to `summarizer`.

### 3. Add tools

Each tool is a FastMCP server in `tools/<tool_name>/main.py`:

```python
from fastmcp import FastMCP

mcp = FastMCP("pdf_reader")

@mcp.tool()
def read_pdf(file_path: str) -> str:
    """Read and extract text from a PDF file."""
    # your implementation
    return extracted_text

if __name__ == "__main__":
    mcp.run()
```

### Tool dependencies

If your tool needs external libraries, add a `requirements.txt` in the tool directory:

```text
tools/
  my_tool/
    main.py
    requirements.txt    # e.g. "requests>=2.28"
```

Or a full `pyproject.toml` for more control. ezagent uses `uv` to run the tool in an isolated environment automatically.

### Prebuilt tools

ezagent ships with prebuilt tools that don't require any local files. Add them to your `agents.yml` tools list by name:

| Tool         | Description                                                                 |
| ------------ | --------------------------------------------------------------------------- |
| `memory`     | Persistent vector-based memory (store, search, delete, list) using Milvus Lite and sentence-transformers |
| `web_search` | Web search and page reading via Brave Search API (requires `BRAVE_SEARCH_API_KEY`) |
| `http`       | Generic HTTP client for interacting with any REST API (no API key required by the tool) |

```yaml
agents:
  assistant:
    tools: greeter, memory
    description: "An assistant with persistent memory"
```

Prebuilt tool dependencies are installed automatically by `uv` in an isolated environment — no manual installation needed.

#### Memory tool

The `memory` tool gives agents five operations:

- **`memory_store(content, collection?, tags?, agent_name?)`** — Store a text memory with optional tags and agent association.
- **`memory_search(query, collection?, top_k?, agent_name?, tags?)`** — Semantic similarity search across stored memories.
- **`memory_delete(memory_id, collection?)`** — Delete a memory by its UUID.
- **`memory_list(collection?, agent_name?, limit?, offset?)`** — Browse stored memories with pagination.
- **`memory_collections()`** — List all existing collections.

All operations accept an optional `collection` parameter (defaults to `"memory"`). Use collections to organize memories into logical groups:

```text
conversations  — chat history and dialogue
patterns       — recurring themes or learned behaviours
facts          — factual knowledge
```

Memories are stored locally in `.ezagent/memory/milvus.db` inside the project directory. Embeddings are generated locally using the `all-MiniLM-L6-v2` model (downloaded on first use, ~90MB).

#### Web search tool

The `web_search` tool gives agents two operations:

- **`web_search(query, count?)`** — Search the web and return results with title, URL, and snippet (default 5 results, max 20).
- **`web_search_read(url)`** — Fetch a URL's text content with HTML stripped, truncated to ~20,000 characters.

Requires a Brave Search API key:

```bash
export BRAVE_SEARCH_API_KEY=your-key-here
```

Get a free API key at [brave.com/search/api](https://brave.com/search/api/).

You can select a different search provider via the `WEB_SEARCH_PROVIDER` env var (default: `"brave"`). Currently only Brave is supported.

```yaml
agents:
  researcher:
    tools: web_search
    description: "An agent that can search the web"
```

#### HTTP tool

The `http` tool gives agents two operations:

- **`http_request(method, url, headers?, body?, params?)`** — Make an HTTP request (GET, POST, PUT, PATCH, DELETE, HEAD). Returns status code, response headers, and body. Auto-detects JSON responses. Timeout: 30 seconds.
- **`http_read(url, headers?)`** — Shorthand GET that strips HTML tags and returns plain text, truncated to ~20,000 characters.

No API key is required by the tool itself — authentication is handled via headers the agent passes (guided by skills).

```yaml
agents:
  api_client:
    tools: http
    description: "An agent that can interact with REST APIs"
```

### 4. Add skills

Skills are markdown files in `skills/` that get injected into the agent's system prompt:

```markdown
<!-- skills/research.md -->
You are an expert researcher. When given a topic:
1. Break it into sub-questions
2. Search for authoritative sources
3. Synthesize findings into a clear answer
```

### 5. Set API keys

Set the key for the provider(s) you plan to use:

```bash
# Anthropic (default provider)
export ANTHROPIC_API_KEY=sk-...

# Google Gemini
export GOOGLE_API_KEY=your-key-here
```

### 6. Run

```bash
# Start the daemon
ez start

# Talk to an agent
ez researcher "What are the latest advances in quantum computing?"

# Stop the daemon
ez stop
```

## CLI Reference

| Command                      | Description                             |
| ---------------------------- | --------------------------------------- |
| `ez init <name>`             | Scaffold a new project                  |
| `ez start`                   | Start the agent daemon (background)     |
| `ez stop`                    | Stop the daemon                         |
| `ez status`                  | Show daemon status and configured agents|
| `ez tools`                   | List available prebuilt and project tools|
| `ez run <agent> <message>`   | Send a message to an agent              |
| `ez <agent> <message>`       | Shorthand for `ez run`                  |

## Providers

ezagent supports multiple LLM providers. Set the provider globally or per-agent in `agents.yml`.

| Provider    | Name in config | Default model              | Env variable        |
| ----------- | -------------- | -------------------------- | ------------------- |
| Anthropic   | `anthropic`    | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| Google Gemini | `google`     | `gemini-2.0-flash`         | `GOOGLE_API_KEY`    |

### Global provider

Set a top-level `provider` and `model` in `agents.yml`. All agents inherit these unless they override them. If omitted, defaults to `anthropic`.

```yaml
provider: google
model: gemini-2.0-flash

agents:
  assistant:
    description: "Uses Gemini"
```

### Per-agent override

Individual agents can use a different provider/model than the global default:

```yaml
provider: google
model: gemini-2.0-flash

agents:
  researcher:
    provider: anthropic
    model: claude-sonnet-4-20250514
    description: "This agent uses Claude"
  assistant:
    description: "This agent inherits Google Gemini from the global config"
```

## Scheduling

Agents can be triggered automatically on a cron schedule. Add a `schedule` list to any agent in `agents.yml`:

```yaml
agents:
  reporter:
    tools: web_search, memory
    description: "Generates daily reports"
    schedule:
      - cron: "0 9 * * *"
        message: "Generate the daily summary report"
      - cron: "0 */4 * * *"
        message: "Check for anomalies"
```

Each entry has:

| Field     | Description                          |
| --------- | ------------------------------------ |
| `cron`    | A standard cron expression (validated on load via [croniter](https://github.com/kiorky/croniter)) |
| `message` | The message sent to the agent when the schedule fires |

The scheduler runs as a background asyncio task inside the daemon alongside the Unix socket server. When the daemon starts, it computes the next run time for every entry and sleeps until the earliest one is due. Scheduled runs are fire-and-forget — they don't block each other or the socket server.

Use `ez status` to see upcoming schedule times:

```
  reporter         anthropic/claude-sonnet-4-5   tools: web_search, memory
    schedule: 0 9 * * *            next: 2026-02-04T09:00:00   "Generate the daily summary report"
    schedule: 0 */4 * * *          next: 2026-02-03T16:00:00   "Check for anomalies"
```

Scheduler logs are written to `.ezagent/scheduler.log` inside the project directory.

## Architecture

- **Daemon**: Background process communicating over a Unix domain socket (`/tmp/ezagent_<hash>.sock`)
- **Agents**: Each agent has a system prompt (built from skills), access to MCP tools, and can delegate to other agents
- **Tools**: FastMCP servers connected via STDIO transport (local tools in `tools/`, prebuilt tools shipped with ezagent)
- **Prebuilt tools**: Built-in tools (e.g. `memory`) that ship with ezagent, run in isolated uv environments with their own dependencies
- **Agent-as-tool**: Agents listed in another agent's `tools` become callable tools with a `{"message": string}` interface
- **Scheduler**: Cron-based background task that fires agent runs on a schedule, running alongside the socket server in the same asyncio event loop
- **LLM**: Provider-agnostic design with an `LLMProvider` ABC; implements Anthropic and Google Gemini

## TODO
* Test Gemini Provider, it's not tested due to missing API key.

## License

MIT

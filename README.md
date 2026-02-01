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

## Architecture

- **Daemon**: Background process communicating over a Unix domain socket (`/tmp/ezagent_<hash>.sock`)
- **Agents**: Each agent has a system prompt (built from skills), access to MCP tools, and can delegate to other agents
- **Tools**: FastMCP servers connected via STDIO transport
- **Agent-as-tool**: Agents listed in another agent's `tools` become callable tools with a `{"message": string}` interface
- **LLM**: Provider-agnostic design with an `LLMProvider` ABC; implements Anthropic and Google Gemini

## TODO
* Test Gemini Provider, it's not tested due to missing API key.

## License

MIT

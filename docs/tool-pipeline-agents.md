## Overview

Agents with `provider: none` run a **fixed tool pipeline** with no LLM. Use them for scheduled ETL, notifications, or any workflow you can express as ordered tool calls.

## How it works

- **`pre_tools`**: Ordered steps that run first. Each step can label its tool output with `as` (a key).
- **`run_tools`**: Steps that run after `pre_tools`. A step can pass the prior step’s output into the next tool via `args_from` (key from `pre_tools` `as`, or another agreed key), so the runtime wires JSON between tools.
- The agent still declares **`tools`** with the tool names used in the pipeline (same as any agent). Tools must be available in the project (local or prebuilt).

## How to use

Minimal pattern (YAML shape; exact `args` / `args_from` depend on your tools):

```yaml
agents:
  nightly_job:
    provider: none
    description: "Ingest and store without LLM"
    tools: fetch_feed, save_items
    pre_tools:
      - id: step1
        tool: fetch_feed
        args: { url: "https://example.com/feed" }
        as: feed_json
    run_tools:
      - tool: save_items
        args_from: feed_json
    schedule:
      - cron: "0 2 * * *"
        message: "nightly"   # stored on the run row; pipeline does not use LLM text
```

On each cron tick the daemon runs the pipeline instead of an LLM loop.

## Gotchas

- **`provider: none`** must be set; otherwise the normal agent loop runs.
- Pipeline wiring is strict: bad `args_from` keys raise at runtime. Prefer small, testable pipelines.
- For full behavior and edge cases, see the tool-only agent tests in `tests/test_tool_only_agent.py`.

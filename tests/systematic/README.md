# Systematic Tests

This directory contains organized systematic tests for ezagent, covering edge cases, error handling, and robustness.

## Test Structure

```
systematic/
├── __init__.py           # Package initialization
├── README.md            # This file
├── test_config.py       # Configuration validation tests
├── test_daemon.py       # Daemon socket handling and scheduler tests
├── test_discussions.py  # Multi-agent discussion tests
├── test_event_log.py    # Event logging and persistence tests
├── test_llm_providers.py # LLM provider implementation tests
└── test_tools.py        # Tool management and MCP client tests
```

## Test Categories

### Configuration (`test_config.py`)
- Configuration validation logic
- Circular reference detection
- Agent/discussion dependency graph validation

### Daemon (`test_daemon.py`)
- Socket handling and cleanup
- Scheduler timezone consistency
- Error response handling

### Discussions (`test_discussions.py`)
- Moderator call parameters
- Discussion source tracking
- Multi-agent coordination

### Event Logging (`test_event_log.py`)
- Concurrent write handling
- Event loop edge cases
- Database integrity

### LLM Providers (`test_llm_providers.py`)
- Google/Gemini tool result mapping
- Anthropic format conversion
- Tool name preservation

### Tools (`test_tools.py`)
- Tool manager lifecycle
- MCP client cleanup
- Error handling in disconnect

## Running Tests

Run all systematic tests:
```bash
uv run pytest tests/systematic/ -v
```

Run a specific test module:
```bash
uv run pytest tests/systematic/test_daemon.py -v
```

Run a specific test class:
```bash
uv run pytest tests/systematic/test_daemon.py::TestDaemonSocketHandling -v
```

## Test Coverage

These tests cover bugs discovered during systematic code review:

1. **Socket Writer Resource Leak** - Daemon properly closes socket writers
2. **Google Provider Tool Mapping** - Tool results use correct function names
3. **Discussion Source Parameter** - Moderator calls include proper source
4. **Tool Manager Cleanup** - Disconnect handles None clients gracefully

All tests include detailed docstrings explaining what they test and why.

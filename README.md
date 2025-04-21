# A2A CLI

A command-line client for the A2A (Agent-to-Agent) Protocol.

## Overview

A2A CLI provides a rich, interactive command-line interface for interacting with A2A protocol servers. It allows you to connect to A2A-compatible agents, send tasks, monitor their progress, and view results in real-time.

## Features

- Interactive chat mode with server agents
- Command-line interface for task management
- Multiple transport protocols (HTTP, SSE, WebSockets, STDIO)
- Rich text UI with streaming responses
- Support for all A2A protocol methods
- Configuration management for multiple servers

## Installation

```bash
# Install from PyPI
pip install a2a-cli

# Or install from source
git clone https://github.com/chrishayuk/a2a-cli.git
cd a2a-cli
pip install -e .
```

## Quick Start

```bash
# Start in interactive chat mode
a2a chat

# Send a task to a server
a2a send "Hello, agent" --server http://localhost:8000

# Watch a task's progress
a2a watch <task-id>
```

## Chat Mode

The interactive chat mode provides a rich interface for interacting with A2A agents:

```bash
a2a chat
```

In chat mode, you can:
- Type messages directly to communicate with the agent
- Use slash commands to perform specific actions
- View agent responses with rich formatting
- Monitor task status and artifacts in real-time

### Common Chat Commands

| Command | Description |
|---------|-------------|
| `/connect <url>` | Connect to an A2A server |
| `/send <text>` | Send a task to the server |
| `/send_subscribe <text>` | Send a task and stream updates |
| `/get <id>` | Get details about a task |
| `/help` | Show available commands |
| `/server` | Show current server information |
| `/servers` | List available server configurations |

## Command Line Mode

A2A CLI can also be used as a traditional command-line tool:

```bash
# Send a task and wait for the result
a2a send "Generate a list of 5 movie recommendations" --wait

# Get details about a specific task
a2a get <task-id>

# Cancel a running task
a2a cancel <task-id>
```

## Configuration

A2A CLI supports configuration files to manage multiple server connections. Create a file at `~/.a2a/config.json`:

```json
{
  "servers": {
    "local": "http://localhost:8000",
    "dev": "https://dev-agent.example.com",
    "prod": "https://agent.example.com"
  }
}
```

Then use them by name:

```bash
a2a chat --server local
```

Or in chat mode:

```
/connect local
```

## Transport Types

A2A CLI supports multiple transport protocols:

- HTTP: Standard JSON-RPC over HTTP
- SSE: Server-Sent Events for streaming responses
- WebSocket: Bidirectional communication
- STDIO: Standard input/output for CLI-based agents

## Development

### Requirements

- Python 3.11+
- Dependencies: a2a-json-rpc, httpx, rich, typer, prompt-toolkit

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/a2a-cli.git
cd a2a-cli

# Install in development mode
make dev-install

# Run tests
make test
```

### Project Structure

```
a2a-cli/
├── src/
│   └── a2a_cli/
│       ├── a2a_client.py   # Main client class
│       ├── cli.py          # CLI entry point
│       ├── transport/      # Transport implementations
│       ├── chat/           # Chat interface
│       └── ui/             # UI components
├── tests/                  # Test suite
├── pyproject.toml          # Project metadata and dependencies
└── README.md               # This file
```

## License

MIT
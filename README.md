# 🌐 MCP AI SSH Agent

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP Protocol](https://img.shields.io/badge/MCP-FastMCP-green.svg)](https://github.com/jlowin/fastmcp)

An intelligent Model Context Protocol (MCP) server for managing remote **SSH sessions**, **interactive shell prompts**, and long-running **background tasks** (via `tmux`).

Designed specifically for AI Assistants (Claude Desktop, Cursor, AI agents) to perform seamless remote administration, task execution, log streaming, and prompt handling over SSH.

---

## ✨ Key Features

- 🔑 **Multi-Session SSH Management**: Password and SSH Key-based authentication with auto-persistence and recovery.
- ⚡ **Synchronous & Asynchronous Execution**:
  - `ssh_execute`: Run standard commands with real-time output and exit codes.
  - `ssh_exec_background`: Spawn detached tasks using `tmux` for long-running processes (e.g., builds, benchmarks, updates).
- 💬 **Interactive Prompt Detection**: Automatically detects prompts requiring user input (`[y/N]`, passwords, confirmation dialogs) and notifies AI.
- 📜 **Log Streaming & Tailing**: Read background task outputs incrementally or in chunks with ANSI-sanitization.
- 🔄 **State Recovery & Persistence**: Automatically saves session metadata and task states to `~/.mcp_ssh/pool.json`, allowing session recovery after restarts.

---

## 🛠️ Architecture Overview

```
                   +---------------------+
                   |   AI Client / Agent |
                   | (Claude, Cursor, ..)|
                   +----------+----------+
                              | MCP (JSON-RPC)
                              v
                   +---------------------+
                   |   FastMCP Server    |
                   | (ssh_server.py)     |
                   +----------+----------+
                              |
       +----------------------+----------------------+
       |                      |                      |
       v                      v                      v
+--------------+      +---------------+      +---------------+
| Session      |      | Task Pool     |      | Task Runner   |
| Manager      |      | Persistence   |      | (tmux / log)  |
+------+-------+      +---------------+      +---------------+
       |
       v
+--------------+
| Paramiko SSH | =====> Remote Server
+--------------+
```

---

## 📦 Installation

### Prerequisites
* Python **3.10+**
* `uv` or `pip`

```bash
# Clone repository
git clone https://github.com/prmgint/mcp-ai-ssh.git
cd mcp-ai-ssh

# Install package locally
pip install -e .
```

---

## ⚙️ Configuration & MCP Setup

Add `mcp-ai-ssh` to your MCP client configuration (e.g., `claude_desktop_config.json`):

### Option 1: Using `uvx` / `pip` entry point
```json
{
  "mcpServers": {
    "mcp-ai-ssh": {
      "command": "mcp-ai-ssh",
      "args": []
    }
  }
}
```

### Option 2: Running directly with `uv`
```json
{
  "mcpServers": {
    "mcp-ai-ssh": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/mcp_ai_ssh_agent",
        "run",
        "mcp-ai-ssh"
      ]
    }
  }
}
```

---

## 🛠️ Available MCP Tools

### 1. Connection & Session Management
- **`ssh_connect`**: Connect to a remote host (`host`, `username`, `password`, `private_key_path`, `port`, `timeout`). Returns `session_id`.
- **`ssh_session_info`**: Retrieve information about an active or persistent session.
- **`ssh_close`**: Close an active SSH session and mark associated tasks as orphaned.
- **`ssh_recover`**: Attempt to reconnect persistent SSH sessions and restore background task tracking.

### 2. Command Execution
- **`ssh_execute`**: Run a command synchronously with output sanitization and prompt detection.
- **`ssh_send_input`**: Send user/AI input to a session currently awaiting an interactive response.

### 3. Background Task Management (`tmux`)
- **`ssh_exec_background`**: Launch a command in a detached `tmux` session.
- **`ssh_task_status`**: Inspect task status (`running`, `completed`, `failed`, `input_required`, `cancelled`).
- **`ssh_task_log`**: Read task output logs incrementally with pagination (`from_offset`, `max_bytes`).
- **`ssh_task_send_input`**: Send input directly to a running background task awaiting interactive input.
- **`ssh_task_cancel`**: Terminate a background task.
- **`ssh_task_list`**: List all tracked background tasks for a session or globally.

---

## 🚀 Usage Example

### 1. Connecting to a Server
```json
// Call ssh_connect
{
  "host": "192.168.1.100",
  "username": "root",
  "auth_type": "key",
  "private_key_path": "~/.ssh/id_ed25519"
}
// Returns: { "session_id": "a1b2c3d4-..." }
```

### 2. Synchronous Command Execution
```json
// Call ssh_execute
{
  "session_id": "a1b2c3d4-...",
  "command": "uname -a && uptime"
}
// Returns: { "status": "completed", "stdout": "Linux server 5.15.0 ...", "exit_code": 0 }
```

### 3. Running a Long-Running Background Task
```json
// Call ssh_exec_background
{
  "session_id": "a1b2c3d4-...",
  "command": "apt-get update && apt-get upgrade -y"
}
// Returns: { "task_id": "t9x8y7...", "pid": 12345, "status": "running" }
```

### 4. Streaming Logs & Responding to Prompts
```json
// Call ssh_task_log
{
  "task_id": "t9x8y7...",
  "from_offset": 0
}

// If task requires confirmation, ssh_task_status returns:
// { "status": "input_required", "awaiting_input": true }

// Call ssh_task_send_input
{
  "task_id": "t9x8y7...",
  "input": "Y\n"
}
```

---

## 🧪 Testing

Run the unit test suite using `pytest`:

```bash
pytest
```

Or execute testing batch scripts:
```cmd
run_tests.bat
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

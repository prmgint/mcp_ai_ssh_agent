# SKILL: MCP SSH Agent

## Purpose
Manage remote SSH sessions and background tasks through MCP tools.

## When to use
- The user asks to run a command on a remote host.
- A long-running task needs to be started and its output streamed.
- An interactive program needs to be driven (y/n prompts, password prompts, REPLs).
- When interacting with interactive programs (y/n, password, REPL): if the required input is ambiguous, do **not** guess — ask the user.

## Tools

### 1. `ssh_connect`
Establishes an SSH connection and returns a `session_id`.

```json
{
  "host": "example.com",
  "username": "root",
  "auth_type": "key",           // "password" | "key"
  "private_key_path": "~/.ssh/id_rsa",
  "private_key_passphrase": null,
  "password": null,
  "auth": null,                 // legacy fallback for password
  "port": 22,
  "timeout": 30
}
```

Returns: ```json{"session_id": "uuid"}```

Rules:
For auth_type="password", use the password field (not auth).
auth is a legacy alias — keep it only for backward compatibility.
Always persist session_id; every other tool depends on it.

### 2. ssh_execute
Runs a command synchronously (default timeout 300s).

```json
{
  "session_id": "uuid",
  "command": "ls -la",
  "timeout": 300
}
```
Returns:

```json
{
  "status": "completed" | "input_required" | "timeout",
  "stdout": "...",
  "exit_code": 0,
  "prompt_text": "..."       // present when status == "input_required"
}
```

Rules:

If status == "input_required" — call ssh_send_input.
If status == "timeout" — the command is long-running; use ssh_exec_background instead.

### 3. ssh_send_input
Replies to an interactive prompt detected by ssh_execute.

```json
{
  "session_id": "uuid",
  "input": "yes",
  "timeout": 30
}
```
Returns the same shape as ssh_execute (may chain into another input_required).

Rules:

Only valid when the previous ssh_execute returned status == "input_required".
If the expected answer is ambiguous — ask the user before sending anything.

### 4. ssh_exec_background
Starts a long-running command in the background using tmux (falls back to nohup).

```json
{
  "session_id": "uuid",
  "command": "python train.py"
}
```
Returns:

```json
{
  "task_id": "uuid",
  "pid": 12345,
  "log_path": "/tmp/mcp_task_<task_id>.log",
  "exit_file": "/tmp/mcp_task_<task_id>.exit",
  "mode": "tmux" | "nohup",
  "status": "running",
  "session_id": "uuid",
  "started_at": "2026-01-01T00:00:00Z"
}
```
Rules:

Prefer this for any command expected to run longer than ~5 minutes.
Read output via ssh_task_log, not ssh_execute("cat ...").

### 5. ssh_task_status
Returns the current status of a background task.

```json
{ "task_id": "uuid" }
```
Returns:

```json
{
  "task_id": "uuid",
  "status": "running" | "completed" | "failed" | "cancelled"
            | "input_required" | "unknown" | "orphaned",
  "exit_code": 0,
  "pid": 12345,
  "started_at": "2026-01-01T00:00:00Z",
  "finished_at": "2026-01-01T00:05:00Z",
  "duration_sec": 300.0
}
```
Rules:

Poll at most once per second.
status == "input_required" means the task is waiting for input — read ssh_task_log to see the prompt, then call ssh_task_send_input.

### 6. ssh_task_log
Incrementally reads a task's log file.

```json
{
  "task_id": "uuid",
  "from_offset": 0,
  "max_bytes": 65536
}
```
Returns:

```json
{
  "task_id": "uuid",
  "chunk": "...",
  "next_offset": 1024,
  "eof": false
}
```
Rules:

Always feed the returned next_offset back into the next call — do not re-read from 0.

### 7. ssh_task_send_input
Sends input to a background task that reported status == "input_required".

```json
{
  "task_id": "uuid",
  "input": "y"
}
```
Rules:

Only valid when ssh_task_status reports input_required.
If the required answer is ambiguous — ask the user first.

### 8. ssh_task_cancel
Terminates a background task (kills the tmux session or the nohup PID).

```json
{ "task_id": "uuid" }
```
Returns: ```json{"task_id": "uuid", "cancelled": true}```

### 9. ssh_task_list
Lists tasks, optionally filtered by session.

```json
{ "session_id": "uuid" }   // optional
```
Returns: ```json{"tasks": [ ... ]}```

### 10. ssh_session_info
Returns persisted metadata for a session.

```json
{ "session_id": "uuid" }
```
Returns:

```json
{
  "session_id": "uuid",
  "host": "example.com",
  "port": 22,
  "username": "root",
  "auth_type": "key"
}
```
### 11. ssh_close
Closes an SSH session.

```json
{ "session_id": "uuid" }
```
Rules:

If the session has running background tasks, they become orphaned.
The persisted session record is removed from the pool.

### 12. ssh_recover
Restores sessions and tasks from ~/.mcp_ssh/pool.json after an MCP restart.

```json
{}
```
Returns:

```json
{
  "recovered_sessions": 1,
  "recovered_tasks": 2,
  "failed": ["Session abc: password auth not supported"]
}
```
Rules:

Key-auth only — password-auth sessions cannot be restored (passwords are never persisted).
Call once on startup, not in a loop.

## Typical workflows
### Workflow A — quick one-shot command

ssh_connect → ssh_execute → ssh_close

### Workflow B — interactive command

ssh_connect
ssh_execute("sudo apt update")
  → status="input_required", prompt_text="[sudo] password:"
  → (if prompt is ambiguous, ask the user)
ssh_send_input("<password>")
  → status="completed"

### Workflow C — long-running task

ssh_connect
ssh_exec_background("python train.py") → task_id
loop:
  status = ssh_task_status(task_id)
  log = ssh_task_log(task_id, from_offset=next_offset)
  next_offset = log["next_offset"]
  if status["status"] in (completed, failed, cancelled): break
  sleep(5)

### Workflow D — background task asks for input

ssh_task_status → status="input_required"
ssh_task_log    → see prompt in the chunk
(if ambiguous — ask the user)
ssh_task_send_input("y")

## Constraints and rules
 1. One session per host is recommended — create separate sessions for parallel work.

 2. ssh_execute default timeout is 300s — for longer commands use ssh_exec_background.

 3. Task logs live at /tmp/mcp_task_<task_id>.log — read them via ssh_task_log.

 4. ssh_close with running tasks returns a warning; the tasks keep running on the server (tmux).

 5. After an MCP restart, call ssh_recover before doing anything else.

 6.Passwords are never persisted — recovery is impossible for auth_type="password".

 7. sanitize_output masks password/token/private key patterns — never treat raw output as safe storage for secrets.

 8. Always check status — timeout is not completed.

 9. exit_code may be null when status == "input_required" or "timeout" — do not treat this as an error.

 10. input_required in background means the task is blocked on input — respond or cancel via ssh_task_cancel.

 11. If the required input is ambiguous — ask the user, do not guess. This applies to ssh_send_input and ssh_task_send_input alike.

## Common errors
────────────────────────────────────────────────────────────────────────────────────────────────────
Error                              | Cause                          | Fix
────────────────────────────────────────────────────────────────────────────────────────────────────
Session not found                  | Session closed or never        | Re-check session_id,
                                   | created                        | call ssh_connect
────────────────────────────────────────────────────────────────────────────────────────────────────
Task not awaiting input            | Task already finished          | Check ssh_task_status
                                   |                                | first
────────────────────────────────────────────────────────────────────────────────────────────────────
status="unknown" for a             | .exit file not written yet     | Wait, inspect
background task                    |                                | ssh_task_log
────────────────────────────────────────────────────────────────────────────────────────────────────
orphaned                           | Session lost after MCP         | ssh_recover or restart
                                   | restart                        | the task
────────────────────────────────────────────────────────────────────────────────────────────────────
timeout in ssh_execute             | Command exceeded timeout       | Use ssh_exec_background
────────────────────────────────────────────────────────────────────────────────────────────────────
password auth not supported        | Password was never persisted   | Use key-based auth
in recover                         |                                |
────────────────────────────────────────────────────────────────────────────────────────────────────

## Best practices for the agent
 1. Always keep session_id and task_id in the conversation context.

 2. Do not poll ssh_task_status more than once per second.

 3. Use from_offset for incremental log reads — never re-read the whole file.

 4. Check status before calling ssh_task_send_input.

 5. Close sessions with ssh_close when finished.

 6. For commands longer than ~5 minutes, always use ssh_exec_background.

 7. Never log the contents of password / auth fields.

 8. On input_required, read prompt_text first, then respond.

 9. Call ssh_recover once at startup — not in a loop.

 10. For parallel tasks, create separate sessions instead of sharing one.

 11. When in doubt about an interactive answer — ask the user.
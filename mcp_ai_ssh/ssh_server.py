import logging
import atexit
import uuid
import os
from typing import Optional, Literal
from datetime import datetime, timezone
from pydantic import SecretStr
from fastmcp import FastMCP
from .ssh_manager import SessionManager
from .ssh_schemas import ConnectParams
from .utils import sanitize_output
from .task_pool import TaskPool
from .pool_persistence import PoolPersistence
from .task_runner import TaskRunner
from .ssh_session import SSHSession

logger = logging.getLogger(__name__)

mcp_app = FastMCP("mcp-ai-ssh")
session_manager = SessionManager()
persistence = PoolPersistence(os.path.expanduser("~/.mcp_ssh/pool.json"))
task_pool = TaskPool(persistence)

@mcp_app.tool()
def ssh_exec_background(session_id: str, command: str) -> dict:
    session = session_manager.get_session(session_id)
    if not session:
        return {"error": "Session not found"}
    if getattr(session, "channel", None) and getattr(session.channel, "closed", False):
        return {"error": "Session channel is closed"}
    try:
        runner = TaskRunner(session)
        task = runner.run_background(command, str(uuid.uuid4()))
        if task.get("status") == "failed":
            return task
        task.update({"session_id": session_id, "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
        task_pool.add_task(task)
        return task
    except Exception as e:
        return {"error": str(e)}

@mcp_app.tool()
def ssh_task_status(task_id: str) -> dict:
    task = task_pool.get_task(task_id)
    if not task:
        return {"error": "Task not found"}
    if task.get("status") == "cancelled":
        return task
    session = session_manager.get_session(task.get("session_id"))
    if not session:
        return {"task_id": task_id, "status": "unknown", "pid": task.get("pid"), "started_at": task.get("started_at")}
    runner = TaskRunner(session)
    status_info = runner.get_status(task_id, mode=task.get("mode", "tmux"))
    status = status_info.get("status")
    exit_code = status_info.get("exit_code")
    if exit_code is not None:
        final_status = "completed" if exit_code == 0 else "failed"
    else:
        final_status = status
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    started_at = task.get("started_at")
    if not started_at:
        return {"task_id": task_id, "status": "unknown", "error": "missing started_at"}
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(now.replace("Z", "+00:00"))
    duration = (end - start).total_seconds()
    updates = {"status": final_status, "duration_sec": duration if final_status != "running" else 0, "exit_code": exit_code}
    if final_status == "input_required":
        updates["awaiting_input"] = True
    elif final_status != "running":
        updates["awaiting_input"] = False
        if not task.get("finished_at"):
            updates["finished_at"] = now
    if final_status == "running" and task.get("log_path"):
        # Read tail of log to detect interactive prompts
        log = runner.read_log_tail(task["log_path"], 65536)
        if log.get("chunk"):
            prompt = session.prompt_detector.detect_interactive_prompt(log["chunk"])
            if prompt:
                updates["awaiting_input"] = True
                updates["status"] = "input_required"
    task_pool.update_task(task_id, updates)
    task = task_pool.get_task(task_id)
    effective_status = task.get("status", final_status)
    return {
        "task_id": task_id,
        "status": effective_status,
        "exit_code": exit_code,
        "pid": task.get("pid"),
        "started_at": task.get("started_at"),
        "finished_at": task.get("finished_at") if effective_status != "running" else None,
        "duration_sec": task.get("duration_sec") if effective_status != "running" else 0
    }

@mcp_app.tool()
def ssh_task_log(task_id: str, from_offset: int = 0, max_bytes: int = 65536) -> dict:
    task = task_pool.get_task(task_id)
    if not task:
        return {"error": "Task not found"}
    log_path = task.get("log_path")
    if not log_path:
        return {"task_id": task_id, "chunk": "", "next_offset": from_offset, "eof": True}
    session = session_manager.get_session(task.get("session_id"))
    if not session:
        return {"error": "Session not found"}
    runner = TaskRunner(session)
    res = runner.read_log(log_path, from_offset, max_bytes)
    raw_chunk = res["chunk"]
    sanitized = sanitize_output(raw_chunk)
    res["task_id"] = task_id
    res["chunk"] = sanitized
    res["raw_length"] = len(raw_chunk.encode("utf-8")) if raw_chunk else 0
    return res

@mcp_app.tool()
def ssh_task_send_input(task_id: str, input: str) -> dict:
    task = task_pool.get_task(task_id)
    if not task:
        return {"error": "Task not found"}
    if task.get("status") not in ("running", "input_required"):
        return {"error": f"Task is not running (status: {task.get('status')})"}
    if not task.get("awaiting_input", False):
        return {"error": "Task not awaiting input"}
    session = session_manager.get_session(task.get("session_id"))
    if not session:
        return {"error": "Session not found"}
    runner = TaskRunner(session)
    res = runner.send_input(task_id, input)
    if res.get("status") == "sent":
        task_pool.update_task(task_id, {"awaiting_input": False})
    return res

@mcp_app.tool()
def ssh_task_cancel(task_id: str) -> dict:
    task = task_pool.get_task(task_id)
    if not task:
        return {"error": "Task not found"}
    session = session_manager.get_session(task.get("session_id"))
    if not session:
        return {"error": "Session not found"}
    runner = TaskRunner(session)
    cancelled = runner.cancel_task(task_id, mode=task.get("mode", "tmux"))
    if cancelled:
        task_pool.update_task(task_id, {"status": "cancelled"})
    return {"task_id": task_id, "cancelled": cancelled}

@mcp_app.tool()
def ssh_task_list(session_id: Optional[str] = None) -> dict:
    tasks = list(task_pool.tasks)
    if session_id:
        tasks = [t for t in tasks if t.get("session_id") == session_id]
    return {"tasks": tasks}

@mcp_app.tool()
def ssh_recover() -> dict:
    task_pool.reload()
    sessions = list(task_pool.sessions)
    tasks = list(task_pool.tasks)
    recovered_sessions = 0
    recovered_tasks = 0
    failed = []

    # Recover sessions
    for s in sessions:
        try:
            if s.get("auth_type") != "key":
                failed.append(f"Session {s.get('session_id')}: password auth not supported")
                continue
            ssh_session = SSHSession(
                host=s.get("host"),
                username=s.get("username"),
                auth_type="key",
                private_key_path=s.get("private_key_path"),
                port=s.get("port", 22)
            )
            if ssh_session.connect(timeout=30):
                session_manager.add_session(s.get("session_id"), ssh_session)
                recovered_sessions += 1
            else:
                failed.append(f"Session {s.get('session_id')}: connection failed")
        except Exception as e:
            failed.append(f"Session {s.get('session_id')}: {e}")

    # Recover tasks
    for t in tasks:
        if t.get("status") in ("completed", "failed", "cancelled"):
            continue
        try:
            session = session_manager.get_session(t.get("session_id"))
            if session:
                runner = TaskRunner(session)
                status_info = runner.get_status(t.get("task_id"), mode=t.get("mode", "tmux"))
                task_pool.update_task(t.get("task_id"), {
                    "status": status_info.get("status"),
                    "exit_code": status_info.get("exit_code")
                })
                recovered_tasks += 1
            else:
                failed.append(f"Task {t.get('task_id')}: session {t.get('session_id')} not recovered")
                task_pool.update_task(t.get("task_id"), {"status": "orphaned"})
        except Exception as e:
            failed.append(f"Task {t.get('task_id')}: {e}")
            task_pool.update_task(t.get("task_id"), {"status": "orphaned"})

    return {
        "recovered_sessions": recovered_sessions,
        "recovered_tasks": recovered_tasks,
        "failed": failed
    }

@mcp_app.tool()
def ssh_session_info(session_id: str) -> dict:
    pool = persistence.load()
    for s in pool.get("sessions", []):
        if s.get("session_id") == session_id:
            return {"session_id": session_id, "host": s.get("host"), "port": s.get("port", 22), "username": s.get("username"), "auth_type": s.get("auth_type")}
    return {"error": "Session not found"}

@mcp_app.tool()
def ssh_connect(host: str, username: str, auth_type: Literal["password", "key"] = "password", password: Optional[str] = None, private_key_path: Optional[str] = None, private_key_passphrase: Optional[str] = None, auth: Optional[str] = None, port: int = 22, timeout: int = 30) -> dict:
    try:
        params = ConnectParams(
            host=host,
            username=username,
            auth_type=auth_type,
            password=SecretStr(password) if password else None,
            private_key_path=private_key_path,
            private_key_passphrase=SecretStr(private_key_passphrase) if private_key_passphrase else None,
            auth=SecretStr(auth) if auth else None,
            port=port,
            timeout=timeout
        )
        session_id = session_manager.connect(
            host=params.host,
            username=params.username,
            auth_type=params.auth_type,
            password=params.get_password(),
            private_key_path=params.private_key_path,
            private_key_passphrase=params.get_passphrase(),
            port=params.port,
            timeout=params.timeout
        )
        session_data = {
            "session_id": session_id,
            "host": params.host,
            "port": params.port,
            "username": params.username,
            "auth_type": params.auth_type,
            "private_key_path": params.private_key_path,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "last_active": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        }
        task_pool.add_session(session_data)
        return {"session_id": session_id}
    except Exception as e:
        return {"error": str(e)}

@mcp_app.tool()
def ssh_execute(session_id: str, command: str, timeout: int = 300) -> dict:
    session = session_manager.get_session(session_id)
    if not session:
        return {"error": "Session not found"}
    out, prompt, status, exit_code = session.execute(command, timeout)
    res = {"status": status, "stdout": sanitize_output(out), "exit_code": exit_code}
    if prompt:
        res["prompt_text"] = prompt
    return res

@mcp_app.tool()
def ssh_send_input(session_id: str, input: str, timeout: int = 30) -> dict:
    session = session_manager.get_session(session_id)
    if not session:
        return {"error": "Session not found"}
    out, prompt, status, exit_code = session.send_input(input, timeout)
    res = {"status": status, "stdout": sanitize_output(out), "exit_code": exit_code}
    if prompt:
        res["prompt_text"] = prompt
    return res

@mcp_app.tool()
def ssh_close(session_id: str) -> dict:
    running = [t for t in task_pool.tasks if t.get("session_id") == session_id and t.get("status") == "running"]
    try:
        session_manager.close_session(session_id)
    except Exception as e:
        return {"error": f"close failed: {e}"}
    
    for t in running:
        task_pool.update_task(t["task_id"], {"status": "orphaned"})
    
    task_pool.remove_session(session_id)
    if running:
        return {"status": "closed", "warning": f"Session closed with {len(running)} active tasks marked as orphaned"}
    return {"status": "closed"}

_cleanup_registered = False

def cleanup():
    session_manager.close_all()

def run():
    global _cleanup_registered
    if not _cleanup_registered:
        atexit.register(cleanup)
        _cleanup_registered = True
    mcp_app.run()

if __name__ == "__main__":
    run()
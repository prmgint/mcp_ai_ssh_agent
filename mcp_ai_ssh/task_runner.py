import os
import logging
import shlex
from typing import Dict, Any, Optional
from .ssh_session import SSHSession

logger = logging.getLogger(__name__)

class TaskRunner:
    def __init__(self, session: SSHSession):
        self.session = session

    def run_background(self, command: str, task_id: str) -> Dict[str, Any]:
        log_path = f"/tmp/mcp_task_{task_id}.log"
        exit_file = f"/tmp/mcp_task_{task_id}.exit"
        pid_file = f"/tmp/mcp_task_{task_id}.pid"
        # Check tmux
        which, _, ec = self.session.exec_command("which tmux 2>/dev/null")
        use_tmux = ec == 0 and which.strip()
        if use_tmux:
            # Run command inside tmux, redirect output
            inner = shlex.quote(f"{command} > {log_path} 2>&1; echo $? > {exit_file}")
            tmux_cmd = f"tmux new-session -d -s mcp_{task_id} bash -c {inner}"
            out, err, rc = self.session.exec_command(tmux_cmd)
            if rc != 0:
                return {"task_id": task_id, "pid": None, "log_path": log_path, "exit_file": exit_file, "mode": "tmux", "status": "failed", "error": err.strip()}
            pid = None
            out, _, rc = self.session.exec_command(f"tmux list-panes -t mcp_{task_id} -F '#{{pane_pid}}' | head -n1")
            if rc == 0 and out:
                try:
                    pid = int(out.strip())
                except Exception:
                    pass
        else:
            # Nohup fallback
            inner = shlex.quote(f"{command} > {log_path} 2>&1; echo $? > {exit_file}")
            nohup_cmd = f"nohup sh -c {inner} & echo $! > {pid_file}"
            out, err, rc = self.session.exec_command(nohup_cmd)
            if rc != 0:
                return {"task_id": task_id, "pid": None, "log_path": log_path, "exit_file": exit_file, "mode": "nohup", "status": "failed", "error": err.strip()}
            pid = None
            out, _, rc = self.session.exec_command(f"cat {pid_file}")
            if rc == 0 and out:
                try:
                    pid = int(out.strip())
                except Exception:
                    pass
        return {"task_id": task_id, "pid": pid, "log_path": log_path, "exit_file": exit_file, "mode": "tmux" if use_tmux else "nohup", "status": "running"}

    def get_status(self, task_id: str, mode: Optional[str] = None) -> Dict[str, Any]:
        exit_file = f"/tmp/mcp_task_{task_id}.exit"
        pid_file = f"/tmp/mcp_task_{task_id}.pid"
        if mode == "nohup":
            out, _, rc = self.session.exec_command(f"cat {pid_file}")
            if rc == 0 and out.strip():
                try:
                    pid = int(out.strip())
                    out, _, rc = self.session.exec_command(f"ps -p {pid} -o pid= 2>/dev/null")
                    if rc == 0 and out.strip():
                        return {"status": "running", "exit_code": None}
                except Exception:
                    pass
            out, _, rc = self.session.exec_command(f"cat {exit_file}")
            if rc == 0 and out.strip():
                try:
                    code = int(out.strip())
                    return {"status": "completed" if code == 0 else "failed", "exit_code": code}
                except Exception:
                    return {"status": "unknown", "exit_code": None}
            return {"status": "unknown", "exit_code": None}
        out, _, rc = self.session.exec_command(f"tmux has-session -t mcp_{task_id} 2>/dev/null")
        if rc == 0:
            return {"status": "running", "exit_code": None}
        out, _, rc = self.session.exec_command(f"cat {exit_file}")
        if rc == 0 and out.strip():
            try:
                code = int(out.strip())
                return {"status": "completed" if code == 0 else "failed", "exit_code": code}
            except Exception:
                return {"status": "unknown", "exit_code": None}
        return {"status": "unknown", "exit_code": None}

    def read_log(self, log_path: str, from_offset: int, max_bytes: int) -> Dict[str, Any]:
        # Simple, robust byte-based read using tail and head
        cmd = f"sh -c 'tail -c +{from_offset + 1} {log_path} | head -c {max_bytes}'"
        out, _, rc = self.session.exec_command(cmd)
        if rc == 0:
            n = len(out.encode("utf-8"))
            if n > 0:
                return {"chunk": out, "next_offset": from_offset + n, "eof": False}
        return {"chunk": "", "next_offset": from_offset, "eof": True}

    def read_log_tail(self, log_path: str, max_bytes: int) -> Dict[str, Any]:
        out, _, rc = self.session.exec_command(f"tail -c {max_bytes} {log_path}")
        if rc == 0 and out:
            n = len(out.encode("utf-8"))
            return {"chunk": out, "next_offset": n, "eof": False}
        return {"chunk": "", "next_offset": 0, "eof": True}

    def send_input(self, task_id: str, input: str) -> Dict[str, Any]:
        # Check if tmux session exists
        check_cmd = f"tmux has-session -t mcp_{task_id} 2>/dev/null"
        _, _, check_rc = self.session.exec_command(check_cmd)
        if check_rc != 0:
            return {"task_id": task_id, "status": "failed", "error": "tmux session not found"}
        cmd = f"tmux send-keys -t mcp_{task_id} -l {shlex.quote(input)}; tmux send-keys -t mcp_{task_id} Enter"
        out, err, rc = self.session.exec_command(cmd)
        return {"task_id": task_id, "status": "sent" if rc == 0 else "failed"}

    def cancel_task(self, task_id: str, mode: Optional[str] = None) -> bool:
        effective_mode = mode or "tmux"
        if effective_mode == "nohup":
            out, _, rc = self.session.exec_command(f"kill $(cat /tmp/mcp_task_{task_id}.pid 2>/dev/null) 2>/dev/null")
            return rc == 0
        out, _, rc = self.session.exec_command(f"tmux kill-session -t mcp_{task_id} 2>/dev/null")
        if rc == 0:
            return True
        if mode is None:
            out, _, rc = self.session.exec_command(f"kill $(cat /tmp/mcp_task_{task_id}.pid 2>/dev/null) 2>/dev/null")
            return rc == 0
        return False
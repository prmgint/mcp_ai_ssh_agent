import os
import paramiko
import select
import time
import logging
import uuid
from typing import Tuple, Optional
from .config import BANNER_IDLE_TIMEOUT, BANNER_TOTAL_TIMEOUT, SELECT_TIMEOUT, MAX_BUFFER_SIZE, RECV_CHUNK_SIZE, SHELL_PROMPT_IDLE_TIMEOUT
from .ssh_detector import PromptDetector

logger = logging.getLogger(__name__)

class SSHSession:
    def __init__(self, host: str, username: str, auth_type: str = "password", password: Optional[str] = None, private_key_path: Optional[str] = None, private_key_passphrase: Optional[str] = None, port: int = 22):
        self.host = host
        self.username = username
        self.auth_type = auth_type
        self.password = password
        self.private_key_path = private_key_path
        self.private_key_passphrase = private_key_passphrase
        self.port = port
        self.client = paramiko.SSHClient()
        self.channel = None
        self.prompt_detector = PromptDetector()
        self.awaiting_input = False

    def connect(self, timeout: int = 30) -> bool:
        try:
            self.client.load_system_host_keys()
            user_known_hosts = os.path.expanduser("~/.ssh/known_hosts")
            if os.path.exists(user_known_hosts):
                try:
                    self.client.load_host_keys(user_known_hosts)
                except Exception as e:
                    logger.warning(f"Failed to load user known_hosts: {e}")
            self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
            connect_kwargs = {
                "hostname": self.host,
                "port": self.port,
                "username": self.username,
                "timeout": timeout,
            }
            if self.auth_type == "key" and self.private_key_path:
                connect_kwargs["key_filename"] = self.private_key_path
                if self.private_key_passphrase:
                    connect_kwargs["passphrase"] = self.private_key_passphrase
            elif self.password:
                connect_kwargs["password"] = self.password
            self.client.connect(**connect_kwargs)
            self.channel = self.client.invoke_shell(term="xterm")
            self.channel.setblocking(False)
            start_time = time.time()
            last_data_time = start_time
            has_data = False
            while time.time() - start_time < BANNER_TOTAL_TIMEOUT:
                r, _, _ = select.select([self.channel], [], [], SELECT_TIMEOUT)
                if r:
                    chunk = self.channel.recv(RECV_CHUNK_SIZE).decode("utf-8", errors="ignore")
                    if chunk:
                        has_data = True
                        last_data_time = time.time()
                if has_data and (time.time() - last_data_time) > BANNER_IDLE_TIMEOUT:
                    break
            return True
        except Exception as e:
            logger.error(f"SSH connection failed to {self.host}:{self.port} - {e}")
            return False
        finally:
            self.password = None
            self.private_key_passphrase = None

    def exec_command(self, command: str, timeout: int = 30) -> Tuple[str, str, int]:
        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
        stdout.channel.settimeout(timeout)
        out_data = stdout.read(MAX_BUFFER_SIZE) if MAX_BUFFER_SIZE else stdout.read()
        err_data = stderr.read(MAX_BUFFER_SIZE) if MAX_BUFFER_SIZE else stderr.read()
        exit_code = stdout.channel.recv_exit_status()
        return out_data.decode("utf-8", errors="ignore"), err_data.decode("utf-8", errors="ignore"), exit_code

    def execute(self, command: str, timeout: int = 300) -> Tuple[str, Optional[str], str, Optional[int]]:
        self.awaiting_input = False
        return self._run_stream(command, timeout, is_input=False)

    def send_input(self, user_input: str, timeout: int = 30) -> Tuple[str, Optional[str], str, Optional[int]]:
        if not self.awaiting_input:
            raise RuntimeError("Session is not awaiting input")
        self.awaiting_input = False
        return self._run_stream(user_input, timeout, is_input=True)

    def _run_stream(self, text_to_send: str, timeout: int, is_input: bool) -> Tuple[str, Optional[str], str, Optional[int]]:
        if not self.channel or self.channel.closed:
            raise RuntimeError("Not connected or channel closed")
        if is_input:
            payload = text_to_send + "\n"
        else:
            payload = text_to_send.strip() + "\n"
        echo_marker = payload.rstrip("\n")
        echo_len = 0
        echo_found = False
        self.channel.send(payload)
        cmd_buffer = ""
        output_chunks = []
        start_time = time.time()
        self.prompt_detector.reset_timer()
        prompt_text = None
        status = "completed"
        exit_code = None
        while time.time() - start_time < timeout:
            r, _, _ = select.select([self.channel], [], [], SELECT_TIMEOUT)
            if r:
                data = self.channel.recv(RECV_CHUNK_SIZE).decode("utf-8", errors="ignore")
                if data:
                    output_chunks.append(data)
                    cmd_buffer += data
                    if len(cmd_buffer) > MAX_BUFFER_SIZE:
                        cmd_buffer = cmd_buffer[-MAX_BUFFER_SIZE:]
                    self.prompt_detector.update_activity()
                    if not echo_found and echo_marker:
                        idx = cmd_buffer.find(echo_marker)
                        if idx >= 0:
                            echo_len = idx + len(echo_marker)
                            echo_found = True
            if self.channel.closed or self.channel.eof_received():
                exit_code = self.channel.recv_exit_status() if self.channel.exit_status_ready() else None
                status = "completed" if exit_code is not None else "unknown"
                self.awaiting_input = False
                break
            if len(cmd_buffer) > echo_len:
                active_buffer = cmd_buffer[echo_len:]
                prompt_text = self.prompt_detector.detect_interactive_prompt(active_buffer)
                if prompt_text:
                    status = "input_required"
                    self.awaiting_input = True
                    break
                if self.prompt_detector.detect_shell_prompt(active_buffer) and self.prompt_detector.is_idle(timeout=SHELL_PROMPT_IDLE_TIMEOUT):
                    status = "completed"
                    break
            if self.channel.exit_status_ready():
                exit_code = self.channel.recv_exit_status()
                status = "completed"
                break
        else:
            status = "timeout"
        return "".join(output_chunks), prompt_text, status, exit_code

    def close(self) -> None:
        self.awaiting_input = False
        try:
            if self.channel and not self.channel.closed:
                self.channel.close()
                start = time.time()
                while not self.channel.closed and time.time() - start < 1.0:
                    time.sleep(0.1)
        except Exception as e:
            logger.debug(f"Error closing channel: {e}")
        try:
            if self.client:
                self.client.close()
        except Exception as e:
            logger.debug(f"Error closing SSH client: {e}")
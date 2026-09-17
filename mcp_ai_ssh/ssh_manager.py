import logging
import uuid
import threading
from typing import Dict, Optional, Literal
from .ssh_session import SSHSession

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, SSHSession] = {}
        self._lock = threading.Lock()

    def connect(
        self,
        host: str,
        username: str,
        auth_type: Literal["password", "key"] = "password",
        password: Optional[str] = None,
        private_key_path: Optional[str] = None,
        private_key_passphrase: Optional[str] = None,
        port: int = 22,
        timeout: int = 30
    ) -> str:
        session_id = str(uuid.uuid4())
        ssh_session = SSHSession(
            host=host,
            username=username,
            auth_type=auth_type,
            password=password,
            private_key_path=private_key_path,
            private_key_passphrase=private_key_passphrase,
            port=port
        )
        if ssh_session.connect(timeout):
            with self._lock:
                self.sessions[session_id] = ssh_session
            logger.info(f"Connected to {host}:{port} as {username} [session_id={session_id}]")
            return session_id
        else:
            ssh_session.close()
            logger.error(f"Connection to {host}:{port} failed")
            raise ConnectionError(f"SSH connection to {host}:{port} failed")

    def add_session(self, session_id: str, session: SSHSession):
        """Add a session to the manager (used during recovery)."""
        with self._lock:
            self.sessions[session_id] = session

    def get_session(self, session_id: str) -> Optional[SSHSession]:
        with self._lock:
            return self.sessions.get(session_id)

    def close_session(self, session_id: str) -> bool:
        with self._lock:
            session = self.sessions.pop(session_id, None)
        if session:
            session.close()
            logger.info(f"Closed session {session_id}")
            return True
        return False

    def close_all(self):
        with self._lock:
            session_items = list(self.sessions.items())
            self.sessions.clear()
        for session_id, session in session_items:
            try:
                session.close()
            except Exception as e:
                logger.debug(f"Error closing session {session_id}: {e}")

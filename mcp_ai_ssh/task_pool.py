import uuid
import threading
import time
import logging
from typing import Dict, List, Optional, Any
from .pool_persistence import PoolPersistence

logger = logging.getLogger(__name__)

class TaskPool:
    def __init__(self, persistence: PoolPersistence):
        self.persistence = persistence
        self.lock = threading.RLock()  # Reentrant lock to avoid deadlock when get_task called from update_task
        data = persistence.load()
        self.tasks: List[Dict[str, Any]] = data.get("tasks", [])
        self.sessions: List[Dict[str, Any]] = data.get("sessions", [])
        self._dirty = False
        self._last_sync = 0.0
        self._sync_interval = 5.0  # seconds

    def add_task(self, task: Dict[str, Any]):
        with self.lock:
            self.tasks.append(task)
            self._dirty = True
            self._maybe_sync()

    def add_session(self, session: Dict[str, Any]):
        """Add a session or update if it exists (upsert)."""
        with self.lock:
            session_id = session.get("session_id")
            # Remove existing session with same ID
            self.sessions = [s for s in self.sessions if s.get("session_id") != session_id]
            # Add new session
            self.sessions.append(session)
            self._dirty = True
            self._maybe_sync()

    def remove_session(self, session_id: str):
        with self.lock:
            self.sessions = [s for s in self.sessions if s.get("session_id") != session_id]
            self._dirty = True
            self._maybe_sync()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            return next((t for t in self.tasks if t["task_id"] == task_id), None)

    def update_task(self, task_id: str, updates: Dict[str, Any]):
        with self.lock:
            task = next((t for t in self.tasks if t["task_id"] == task_id), None)
            if task:
                task.update(updates)
                self._dirty = True
                self._maybe_sync()

    def reload(self):
        """Reload data from persistence, replacing in-memory state."""
        with self.lock:
            data = self.persistence.load()
            self.tasks = list(data.get("tasks", []))
            self.sessions = list(data.get("sessions", []))
            self._dirty = False
            self._last_sync = time.time()

    def _maybe_sync(self):
        current_time = time.time()
        if self._dirty and (current_time - self._last_sync) >= self._sync_interval:
            # Take a snapshot of the current state to avoid holding the lock during the potentially slow save
            tasks_snapshot = list(self.tasks)
            sessions_snapshot = list(self.sessions)
            self._dirty = False
            self._last_sync = current_time
            # Release the lock before saving to avoid blocking other operations
            # Note: We release the lock after the with block, so we are safe.
            pass  # We'll do the save after releasing the lock
        else:
            tasks_snapshot = None
            sessions_snapshot = None

        # If we have a snapshot to save, do it now (without holding the lock)
        if tasks_snapshot is not None:
            try:
                self.persistence.save({"version": 1, "tasks": tasks_snapshot, "sessions": sessions_snapshot})
            except Exception as e:
                logger.error(f"Failed to persist task pool: {e}")
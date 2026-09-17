import json
import os
import tempfile
import threading
from typing import Dict, Any

class PoolPersistence:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.lock = threading.Lock()
        self._ensure_file()

    def _ensure_file(self):
        dir_name = os.path.dirname(self.filepath) or "."
        os.makedirs(dir_name, exist_ok=True)
        try:
            with open(self.filepath, 'x', encoding='utf-8') as f:
                json.dump({"version": 1, "tasks": [], "sessions": []}, f, indent=2)
            try:
                os.chmod(self.filepath, 0o600)
            except (OSError, AttributeError):
                # Windows may not support Unix-style chmod
                pass
        except FileExistsError:
            pass

    def save(self, data: Dict[str, Any]):
        with self.lock:
            dir_name = os.path.dirname(self.filepath) or "."
            with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
                json.dump(data, tf, indent=2)
                tf.flush()
                os.fsync(tf.fileno())
                temp_path = tf.name
            os.replace(temp_path, self.filepath)
            # fsync the directory to ensure the rename is durable
            try:
                dir_fd = os.open(dir_name, os.O_RDONLY)
                os.fsync(dir_fd)
                os.close(dir_fd)
            except OSError:
                pass

    def load(self) -> Dict[str, Any]:
        with self.lock:
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return {"version": 1, "tasks": [], "sessions": []}
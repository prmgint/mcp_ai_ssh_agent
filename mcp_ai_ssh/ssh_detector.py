import re
import time
from typing import Optional
from .config import IDLE_TIMEOUT

class PromptDetector:
    INTERACTIVE_PATTERNS = [
        re.compile(r"(?:password|passphrase)[^\n:]*:\s*$", re.IGNORECASE),
        re.compile(r"[\[\(](?:y(?:es)?|n(?:o)?)(?:[/|](?:y(?:es)?|n(?:o)?))?[\]\)]\s*$", re.IGNORECASE),
        re.compile(r"yes/no\b\s*$", re.IGNORECASE),
        re.compile(r"login[^\n:]*:\s*$", re.IGNORECASE),
        re.compile(r"username[^\n:]*:\s*$", re.IGNORECASE),
        re.compile(r"enter\s+[^\n]+:\s*$", re.IGNORECASE),
        re.compile(r">>>\s*$"),  # Python REPL
        re.compile(r"mysql>\s*$"),  # MySQL
        re.compile(r"sqlite>\s*$"),  # SQLite
        re.compile(r"\w+=#\s*$"),   # psql
        re.compile(r"\w+=>\s*$"),   # psql continuation
    ]

    def __init__(self):
        self.last_data_time = time.time()

    def reset_timer(self):
        self.last_data_time = time.time()

    def update_activity(self):
        self.last_data_time = time.time()

    def is_idle(self, timeout: float = IDLE_TIMEOUT) -> bool:
        return (time.time() - self.last_data_time) > timeout

    def detect_interactive_prompt(self, buffer: str) -> Optional[str]:
        """Detect interactive prompt requiring user input. Returns the matched prompt text or None."""
        if not buffer:
            return None
        # Normalize line endings for consistent matching
        normalized = buffer.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.rstrip("\n").splitlines()
        if not lines:
            return None
        last_line = lines[-1]
        stripped = last_line.rstrip()

        for pattern in self.INTERACTIVE_PATTERNS:
            if pattern.search(stripped):
                return stripped
        return None

    def detect_shell_prompt(self, buffer: str) -> bool:
        """Check if output ends with a shell prompt ($ / # / >) followed by a space, indicating command completion."""
        if not buffer:
            return False
        # Normalize line endings for consistent matching
        normalized = buffer.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.rstrip("\n").splitlines()
        if not lines:
            return False
        last_line = lines[-1]
        # Check for common shell prompt endings
        return re.search(r'[$#>]\s+$', last_line) is not None
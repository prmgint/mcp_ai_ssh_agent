import re

SENSITIVE_PATTERNS = [
    (
        r"(?i)(password|passwd|secret|token|access_key|secret_key)\s*[:=]\s*"
        r"(?!true\b|false\b|null\b|none\b)"
        r"(?:\"([^\"\n]{2,})\"|'([^'\n]{2,})'|([^\s\n]{2,}))",
        r"\1: [REDACTED]"
    ),
    (r"(ssh-(rsa|ed25519|dss)|ecdsa-sha2-[a-z0-9]+)\s+[A-Za-z0-9+/]+[=]{0,2}", r"\1: [REDACTED]"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "PRIVATE KEY: [REDACTED]"),
]

def sanitize_output(text: str) -> str:
    """Mask sensitive data in output."""
    sanitized = text
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.DOTALL | re.MULTILINE)
    return sanitized
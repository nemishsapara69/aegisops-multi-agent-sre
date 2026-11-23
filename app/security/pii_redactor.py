import re
from typing import Dict, Tuple

# (label, pattern, replacement). An empty replacement means "[LABEL_REDACTED]".
# Order matters: connection strings are handled before emails.
PATTERNS = [
    ("CONN_STRING", re.compile(r"\b([a-z][a-z0-9+.\-]*://[^\s:/@]+:)[^\s@/]+@", re.I),
     r"\1[PASSWORD_REDACTED]@"),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), ""),
    ("API_KEY", re.compile(r"\b(?:gsk|sk|pk|xai|ghp|api|key|token)[-_][A-Za-z0-9_\-]{12,}\b", re.I), ""),
    ("AWS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), ""),
    ("IPV4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), ""),
    ("SECRET_ASSIGN", re.compile(r"\b(password|passwd|pwd|secret)\s*[=:]\s*[^\s,;]+", re.I),
     r"\1=[SECRET_REDACTED]"),
]


def redact(text: str) -> Tuple[str, Dict[str, int]]:
    counts = {}
    for label, pattern, replacement in PATTERNS:
        text, n = pattern.subn(replacement or "[" + label + "_REDACTED]", text)
        if n:
            counts[label] = n
    return text, counts
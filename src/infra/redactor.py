"""Sensitive data redaction for cloud backends.

Applied to tool results before they are added to the LLM context when using
a cloud backend (groq, gemini, ollama_cloud).  Prevents API keys, passwords,
tokens and private keys from leaving the local machine.
"""
from __future__ import annotations
import re

_PATTERNS: list[tuple[str, str]] = [
    # Generic (.env and config style)
    (
        r'(?i)(api[_-]?key|apikey|secret[_-]?key|access[_-]?key|auth[_-]?token'
        r'|private[_-]?key|client[_-]?secret|password|passwd|pwd|token|credentials)'
        r'\s*[=:]\s*([^\s\n"\'`]{6,})',
        r'\1=***',
    ),
    # Bearer / Authorization headers
    (r'(?i)(Bearer|Basic|Token)\s+[A-Za-z0-9\-._~+/]{20,}={0,2}', r'\1 ***'),
    # Known prefix patterns:
    (
        r'(sk-|gsk_|tvly-|AIzaSy|xoxp-|xoxb-|xoxa-|ollama_|ghp_|gho_|ghs_|glpat-)'
        r'[A-Za-z0-9\-_]{10,}',
        r'\1***',
    ),
    # PEM private keys (multiline)
    (
        r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----',
        '-----BEGIN PRIVATE KEY-----\n***REDACTED***\n-----END PRIVATE KEY-----',
    ),
]

_COMPILED = [(re.compile(p, re.MULTILINE), r) for p, r in _PATTERNS]

SENSITIVE_FILENAMES: frozenset[str] = frozenset({
    ".env", ".env.local", ".env.production", ".env.development", ".env.test",
    "credentials.json", "gcp-oauth.keys.json", "service-account.json",
    ".netrc", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    ".pgpass", ".npmrc", ".pypirc",
})

CLOUD_BACKENDS: frozenset[str] = frozenset({"groq", "gemini", "ollama_cloud"})


def should_redact(backend: str) -> bool:
    return backend in CLOUD_BACKENDS


def is_sensitive_path(path: str) -> bool:
    from pathlib import Path
    name = Path(path).name
    return name in SENSITIVE_FILENAMES or name.startswith(".env")


def redact(text: str) -> str:
    """Apply all redaction patterns to *text* and return the sanitised string."""
    for compiled, replacement in _COMPILED:
        text = compiled.sub(replacement, text)
    return text

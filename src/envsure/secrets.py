"""Detect real-looking credentials in files that are meant to be committed."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Order matters: more specific patterns first (sk-ant- before generic sk-).
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI API key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}")),
    ("Stripe live key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}")),
    ("AWS access key ID", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("Groq API key", re.compile(r"\bgsk_[A-Za-z0-9]{30,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("Password in URL", re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:([^/\s@]{3,})@")),
]

# Values that look like placeholders are never reported.
_PLACEHOLDER_RE = re.compile(
    r"(x{4,}|\*{3,}|<[^>]+>|\$\{[^}]+\}|your[_-]?|change[_-]?me|example|placeholder|dummy|redacted|replace)",
    re.IGNORECASE,
)

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox", ".mypy_cache"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".whl", ".ico", ".woff", ".woff2", ".lock"}


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    masked: str


def mask(secret: str) -> str:
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * min(12, len(secret) - 8)}{secret[-4:]}"


def scan_text(text: str, path: str = "<string>") -> list[Finding]:
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if "envsure: ignore" in line:
            continue
        taken: list[tuple[int, int]] = []
        for kind, pattern in PATTERNS:
            for m in pattern.finditer(line):
                span = m.span(1) if kind == "Password in URL" else m.span()
                secret = line[span[0] : span[1]]
                if any(s < span[1] and span[0] < e for s, e in taken):
                    continue
                if _PLACEHOLDER_RE.search(secret):
                    continue
                taken.append(span)
                findings.append(Finding(path, lineno, kind, mask(secret)))
    return findings


def iter_files(paths: list[str]):
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not (set(f.parts) & SKIP_DIRS) and f.suffix.lower() not in SKIP_SUFFIXES:
                    yield f


def scan_paths(paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for f in iter_files(paths):
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(scan_text(text, str(f)))
    return findings

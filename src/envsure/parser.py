"""Minimal, dependency-free .env parser that keeps line numbers and comments."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


@dataclass
class Entry:
    key: str
    value: str
    line: int
    comment: str = ""  # inline comment text, without the leading '#'
    leading_comments: list[str] = field(default_factory=list)  # full-line comments right above


class ParseError(ValueError):
    def __init__(self, path: str, line: int, message: str):
        super().__init__(f"{path}:{line}: {message}")
        self.path, self.line, self.message = path, line, message


def _split_value(raw: str) -> tuple[str, str]:
    """Return (value, inline_comment) for the right-hand side of KEY=..."""
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        quote = raw[0]
        i, out = 1, []
        while i < len(raw):
            ch = raw[i]
            if ch == "\\" and quote == '"' and i + 1 < len(raw):
                nxt = raw[i + 1]
                out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, "\\" + nxt))
                i += 2
                continue
            if ch == quote:
                rest = raw[i + 1 :].strip()
                comment = rest[1:].strip() if rest.startswith("#") else ""
                return "".join(out), comment
            out.append(ch)
            i += 1
        raise ValueError("unterminated quoted value")
    # Unquoted: an inline comment starts at ' #' (or '#' at the very start).
    if raw.startswith("#"):
        return "", raw[1:].strip()
    m = re.search(r"\s#", raw)
    if m:
        return raw[: m.start()].strip(), raw[m.end() :].strip()
    return raw, ""


def parse_text(text: str, path: str = "<string>") -> list[Entry]:
    entries: list[Entry] = []
    pending_comments: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            pending_comments = []
            continue
        if stripped.startswith("#"):
            pending_comments.append(stripped[1:].strip())
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        if "=" not in stripped:
            raise ParseError(path, lineno, f"expected KEY=VALUE, got {stripped!r}")
        key, raw = stripped.split("=", 1)
        key = key.strip()
        if not _KEY_RE.match(key):
            raise ParseError(path, lineno, f"invalid key name {key!r}")
        try:
            value, comment = _split_value(raw)
        except ValueError as exc:
            raise ParseError(path, lineno, str(exc)) from None
        entries.append(Entry(key, value, lineno, comment, pending_comments))
        pending_comments = []
    return entries


def parse_file(path: str | Path) -> list[Entry]:
    p = Path(path)
    return parse_text(p.read_text(encoding="utf-8"), str(p))


def to_dict(entries: list[Entry]) -> dict[str, str]:
    """Later duplicates win, like most dotenv loaders."""
    return {e.key: e.value for e in entries}

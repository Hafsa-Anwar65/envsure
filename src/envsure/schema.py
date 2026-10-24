"""Turn annotated .env.example lines into a typed schema.

Annotations live in the inline comment, inside square brackets:

    PORT=8000            # [int] port the API listens on
    DEBUG=false          # [bool, optional]
    DATABASE_URL=        # [url] postgres connection string
    LOG_LEVEL=info       # [choice=debug|info|warning|error, optional]

Keys without annotations are treated as required strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .parser import Entry

TYPES = ("str", "int", "float", "bool", "url", "email", "port", "json")
_TRUE = {"1", "true", "yes", "on", "y"}
_FALSE = {"0", "false", "no", "off", "n"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ANNOT_RE = re.compile(r"^\[([^\]]*)\]\s*(.*)$")


class SchemaError(ValueError):
    pass


@dataclass
class Field:
    key: str
    type: str = "str"
    required: bool = True
    default: str = ""
    choices: tuple[str, ...] = ()
    description: str = ""
    line: int = 0


def parse_annotation(comment: str) -> tuple[dict, str]:
    """Return (options, description) from an inline comment."""
    m = _ANNOT_RE.match(comment.strip())
    if not m:
        return {}, comment.strip()
    opts: dict = {}
    for token in (t.strip() for t in m.group(1).split(",")):
        if not token:
            continue
        low = token.lower()
        if low in TYPES:
            opts["type"] = low
        elif low == "optional":
            opts["required"] = False
        elif low == "required":
            opts["required"] = True
        elif low.startswith(("choice=", "choices=")):
            opts["choices"] = tuple(c.strip() for c in token.split("=", 1)[1].split("|") if c.strip())
        else:
            raise SchemaError(f"unknown annotation {token!r} (allowed: {', '.join(TYPES)}, optional, required, choice=a|b)")
    return opts, m.group(2).strip()


def build_schema(entries: list[Entry]) -> dict[str, Field]:
    schema: dict[str, Field] = {}
    for e in entries:
        try:
            opts, desc = parse_annotation(e.comment)
        except SchemaError as exc:
            raise SchemaError(f"line {e.line} ({e.key}): {exc}") from None
        if not desc and e.leading_comments:
            desc = " ".join(e.leading_comments)
        schema[e.key] = Field(key=e.key, default=e.value, description=desc, line=e.line, **opts)
    return schema


def coerce(field: Field, raw: str):
    """Convert a raw string to the field's type. Raises ValueError with a readable message."""
    t = field.type
    if field.choices and raw not in field.choices:
        raise ValueError(f"must be one of {', '.join(field.choices)}")
    if t == "str":
        return raw
    if t == "int":
        try:
            return int(raw)
        except ValueError:
            raise ValueError("must be an integer") from None
    if t == "float":
        try:
            return float(raw)
        except ValueError:
            raise ValueError("must be a number") from None
    if t == "bool":
        low = raw.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise ValueError("must be a boolean (true/false, 1/0, yes/no, on/off)")
    if t == "port":
        try:
            n = int(raw)
        except ValueError:
            raise ValueError("must be a port number") from None
        if not 1 <= n <= 65535:
            raise ValueError("must be a port between 1 and 65535")
        return n
    if t == "url":
        u = urlparse(raw)
        if not u.scheme or not (u.netloc or u.path and u.scheme in ("sqlite", "file")):
            raise ValueError("must be a URL like https://host or postgres://user@host/db")
        return raw
    if t == "email":
        if not _EMAIL_RE.match(raw):
            raise ValueError("must be an email address")
        return raw
    if t == "json":
        import json

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"must be valid JSON ({exc.msg})") from None
    raise ValueError(f"unknown type {t}")  # pragma: no cover

"""check / sync / load — the main envsure operations."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .parser import parse_file, to_dict
from .schema import Field, build_schema, coerce
from .secrets import scan_text


@dataclass
class Issue:
    kind: str  # missing | empty | invalid | extra | secret | duplicate
    key: str
    message: str
    severity: str = "error"  # error | warning
    line: int = 0

    def __str__(self) -> str:
        return f"{self.severity.upper():7} {self.kind:9} {self.key}: {self.message}"


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    checked: int = 0

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "issues": [i.__dict__ for i in self.issues],
        }


class EnvsureError(Exception):
    """Raised by load() when the environment does not match the schema."""

    def __init__(self, report: Report):
        self.report = report
        lines = "\n  ".join(str(i) for i in report.errors)
        super().__init__(f"{len(report.errors)} environment problem(s):\n  {lines}")


class Config(dict):
    """A dict that also allows attribute access: cfg.PORT."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


def _load_schema(example: str | Path) -> dict[str, Field]:
    p = Path(example)
    if not p.exists():
        raise FileNotFoundError(f"schema file not found: {p}")
    return build_schema(parse_file(p))


def _collect_values(env: str | Path | None, use_environ: bool, report: Report) -> dict[str, str]:
    values: dict[str, str] = {}
    if env is not None:
        p = Path(env)
        if p.exists():
            entries = parse_file(p)
            seen: dict[str, int] = {}
            for e in entries:
                if e.key in seen:
                    report.issues.append(
                        Issue(
                            "duplicate",
                            e.key,
                            f"defined on lines {seen[e.key]} and {e.line}; the last one wins",
                            "warning",
                            e.line,
                        )
                    )
                seen[e.key] = e.line
            values.update(to_dict(entries))
        elif not use_environ:
            report.issues.append(
                Issue("missing", str(p), "env file not found (use --environ to read the process environment instead)")
            )
    if use_environ:
        values.update(os.environ)
    return values


def check(
    env: str | Path | None = ".env",
    example: str | Path = ".env.example",
    *,
    use_environ: bool = False,
    strict: bool = False,
    scan_example: bool = True,
) -> Report:
    """Validate an env file (and/or os.environ) against an annotated .env.example."""
    report = Report()
    schema = _load_schema(example)
    values = _collect_values(env, use_environ, report)
    report.checked = len(schema)

    for key, f in schema.items():
        if key not in values:
            if f.required:
                report.issues.append(Issue("missing", key, _with_desc("not set", f), line=f.line))
            continue
        raw = values[key]
        if raw == "":
            if f.required:
                report.issues.append(Issue("empty", key, _with_desc("is empty", f), line=f.line))
            continue
        try:
            coerce(f, raw)
        except ValueError as exc:
            report.issues.append(Issue("invalid", key, f"{exc} (got {_preview(raw)})", line=f.line))

    if env is not None and Path(env).exists():
        for key in to_dict(parse_file(env)):
            if key not in schema:
                report.issues.append(
                    Issue("extra", key, f"not documented in {Path(example).name}", "error" if strict else "warning")
                )

    if scan_example:
        ex = Path(example)
        for finding in scan_text(ex.read_text(encoding="utf-8"), str(ex)):
            report.issues.append(
                Issue(
                    "secret",
                    f"{ex.name}:{finding.line}",
                    f"{finding.kind} committed in example file ({finding.masked})",
                    line=finding.line,
                )
            )
    return report


def load(
    example: str | Path = ".env.example",
    env: str | Path | None = ".env",
    *,
    environ_wins: bool = True,
    export: bool = True,
) -> Config:
    """Validate and return typed settings. Raises EnvsureError listing every problem at once.

    Values already in os.environ override the .env file (12-factor style) unless
    environ_wins=False. With export=True, values from the file are copied into
    os.environ for keys that are not already set.
    """
    schema = _load_schema(example)
    report = Report(checked=len(schema))
    file_values: dict[str, str] = {}
    if env is not None and Path(env).exists():
        file_values = to_dict(parse_file(env))
    if environ_wins:
        values = {**file_values, **{k: v for k, v in os.environ.items() if k in schema}}
    else:
        values = {**{k: v for k, v in os.environ.items() if k in schema}, **file_values}

    cfg = Config()
    for key, f in schema.items():
        raw = values.get(key, "")
        if raw == "":
            if f.required:
                kind = "missing" if key not in values else "empty"
                report.issues.append(Issue(kind, key, _with_desc("not set" if kind == "missing" else "is empty", f)))
                continue
            raw = f.default
            if raw == "":
                cfg[key] = None
                continue
        try:
            cfg[key] = coerce(f, raw)
        except ValueError as exc:
            report.issues.append(Issue("invalid", key, f"{exc} (got {_preview(raw)})"))

    if report.errors:
        raise EnvsureError(report)
    if export:
        for key, raw in file_values.items():
            if key in schema:
                os.environ.setdefault(key, raw)
    return cfg


_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")


def guess_type(value: str) -> str:
    v = value.strip()
    if not v:
        return ""
    if v.lower() in ("true", "false", "yes", "no", "on", "off"):
        return "bool"
    if _INT_RE.match(v):
        return "int"
    if _FLOAT_RE.match(v):
        return "float"
    if re.match(r"^[a-z][a-z0-9+.-]*://", v, re.IGNORECASE):
        return "url"
    if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
        return "email"
    return ""


@dataclass
class SyncResult:
    added: list[str]
    removed: list[str]
    text: str
    changed: bool


def sync(
    env: str | Path = ".env", example: str | Path = ".env.example", *, prune: bool = False, write: bool = True
) -> SyncResult:
    """Add keys that exist in env but not in example — with values blanked — keeping everything else intact."""
    env_entries = parse_file(env)
    ex_path = Path(example)
    ex_text = ex_path.read_text(encoding="utf-8") if ex_path.exists() else ""
    ex_entries = parse_file(ex_path) if ex_path.exists() else []
    ex_keys = {e.key for e in ex_entries}
    env_keys = {e.key for e in env_entries}

    lines = ex_text.splitlines()
    removed: list[str] = []
    if prune:
        drop = {e.line for e in ex_entries if e.key not in env_keys}
        removed = [e.key for e in ex_entries if e.key not in env_keys]
        lines = [ln for i, ln in enumerate(lines, start=1) if i not in drop]

    added: list[str] = []
    new_lines: list[str] = []
    for e in env_entries:
        if e.key in ex_keys or e.key in added:
            continue
        added.append(e.key)
        for c in e.leading_comments:
            new_lines.append(f"# {c}")
        t = guess_type(e.value)
        new_lines.append(f"{e.key}=" + (f"  # [{t}]" if t else ""))

    if new_lines:
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append("")
        lines.extend(new_lines)
    text = "\n".join(lines) + ("\n" if lines else "")
    changed = text != ex_text
    if write and changed:
        ex_path.write_text(text, encoding="utf-8")
    return SyncResult(added, removed, text, changed)


def _with_desc(msg: str, f: Field) -> str:
    return f"{msg} — {f.description}" if f.description else msg


def _preview(raw: str) -> str:
    """Show short, non-secret-looking values; mask the rest."""
    if len(raw) <= 12 and not scan_text(raw):
        return repr(raw)
    return repr(raw[:3] + "…")

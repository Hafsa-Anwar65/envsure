"""Command-line interface: envsure check | sync | scan."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .core import check, sync
from .parser import ParseError
from .schema import SchemaError
from .secrets import scan_paths


def _color(text: str, code: str) -> str:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def cmd_check(args) -> int:
    env = None if args.no_file else args.env
    report = check(env, args.example, use_environ=args.environ, strict=args.strict, scan_example=not args.no_scan)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.ok else 1
    for issue in report.issues:
        color = "31" if issue.severity == "error" else "33"
        print(_color(str(issue), color))
    summary = f"{report.checked} keys checked, {len(report.errors)} error(s), {len(report.warnings)} warning(s)"
    print(_color(("✔ " if report.ok else "✘ ") + summary, "32" if report.ok else "31"))
    return 0 if report.ok else 1


def cmd_sync(args) -> int:
    result = sync(args.env, args.example, prune=args.prune, write=not args.check)
    if args.check:
        if result.changed:
            print(
                f"{args.example} is out of date: missing {', '.join(result.added) or '-'}"
                + (f"; stale {', '.join(result.removed)}" if result.removed else "")
            )
            print("Run `envsure sync` to update it.")
            return 1
        print(f"{args.example} is up to date.")
        return 0
    if not result.changed:
        print(f"{args.example} is already up to date.")
        return 0
    if result.added:
        print(f"Added to {args.example} (values blanked): {', '.join(result.added)}")
    if result.removed:
        print(f"Removed from {args.example}: {', '.join(result.removed)}")
    return 0


def cmd_scan(args) -> int:
    findings = scan_paths(args.paths or ["."])
    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2))
    else:
        for f in findings:
            print(_color(f"{f.path}:{f.line}  {f.kind}  {f.masked}", "31"))
        if findings:
            print(
                _color(
                    f"✘ {len(findings)} possible secret(s) found. Add `envsure: ignore` to a line to silence a false positive.",
                    "31",
                )
            )
        else:
            print(_color("✔ no secrets found", "32"))
    return 1 if findings else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="envsure", description="Keep .env files honest: validate, sync and scan for leaked secrets.")
    p.add_argument("--version", action="version", version=f"envsure {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="validate .env against an annotated .env.example")
    c.add_argument("--env", default=".env", help="env file to validate (default: .env)")
    c.add_argument("--example", default=".env.example", help="schema file (default: .env.example)")
    c.add_argument("--environ", action="store_true", help="also read values from the process environment (for CI/containers)")
    c.add_argument("--no-file", action="store_true", help="ignore the env file; validate the process environment only")
    c.add_argument("--strict", action="store_true", help="treat undocumented keys in .env as errors")
    c.add_argument("--no-scan", action="store_true", help="skip the secret scan of the example file")
    c.add_argument("--json", action="store_true", help="machine-readable output")
    c.set_defaults(func=cmd_check)

    s = sub.add_parser("sync", help="add keys from .env to .env.example with values blanked")
    s.add_argument("--env", default=".env")
    s.add_argument("--example", default=".env.example")
    s.add_argument("--prune", action="store_true", help="also remove keys that no longer exist in .env")
    s.add_argument("--check", action="store_true", help="don't write; exit 1 if the example is out of date (CI / pre-commit)")
    s.set_defaults(func=cmd_sync)

    sc = sub.add_parser("scan", help="scan files or folders for leaked API keys and credentials")
    sc.add_argument("paths", nargs="*", help="files or folders (default: current folder)")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(func=cmd_scan)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "no_file", False):
        args.environ = True
    try:
        return args.func(args)
    except (FileNotFoundError, ParseError, SchemaError) as exc:
        print(_color(f"envsure: {exc}", "31"), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

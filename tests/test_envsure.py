import json
import os

import pytest

from envsure import EnvsureError, check, load, scan_text, sync
from envsure.cli import main
from envsure.parser import ParseError, parse_text
from envsure.schema import SchemaError, build_schema

# Fake tokens are assembled at runtime so this file never contains a literal secret.
FAKE_GH = "ghp_" + "A1b2C3d4E5" * 4
FAKE_OPENAI = "sk-proj-" + "Zx9Yw8Vu7T" * 3
FAKE_ANTHROPIC = "sk-ant-api03-" + "Qq1Rr2Ss3T" * 3
FAKE_AWS = "AKIA" + "QWERTYUIOP123456"

EXAMPLE = """\
# Port the API listens on
PORT=8000          # [port]
DEBUG=false        # [bool, optional]
DATABASE_URL=      # [url] postgres connection string
LOG_LEVEL=info     # [choice=debug|info|warning, optional]
OPENAI_API_KEY=    # your key from the dashboard
TIMEOUT=2.5        # [float, optional]
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.example").write_text(EXAMPLE)
    for k in ("PORT", "DEBUG", "DATABASE_URL", "LOG_LEVEL", "OPENAI_API_KEY", "TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


# ---------- parser ----------


def test_parser_handles_quotes_comments_export():
    entries = parse_text('export A=1\nB="hello # not a comment" # real\nC=\'x y\'\nD=plain # c\nE=a#b\nF="line\\nbreak"\n')
    d = {e.key: e.value for e in entries}
    assert d == {"A": "1", "B": "hello # not a comment", "C": "x y", "D": "plain", "E": "a#b", "F": "line\nbreak"}
    assert entries[1].comment == "real"


def test_parser_errors_have_line_numbers():
    with pytest.raises(ParseError, match=":2:"):
        parse_text("A=1\nnot a pair\n", ".env")
    with pytest.raises(ParseError, match="unterminated"):
        parse_text('A="open\n')


def test_schema_annotations_and_descriptions():
    schema = build_schema(parse_text(EXAMPLE))
    assert schema["PORT"].type == "port" and schema["PORT"].required
    assert schema["PORT"].description == "Port the API listens on"
    assert not schema["DEBUG"].required and schema["DEBUG"].type == "bool"
    assert schema["LOG_LEVEL"].choices == ("debug", "info", "warning")
    assert schema["OPENAI_API_KEY"].type == "str" and schema["OPENAI_API_KEY"].description.startswith("your key")


def test_unknown_annotation_rejected():
    with pytest.raises(SchemaError, match="unknown annotation"):
        build_schema(parse_text("A=1 # [integer]\n"))


# ---------- check ----------


def test_check_reports_everything(project):
    (project / ".env").write_text("PORT=99999\nDATABASE_URL=not-a-url\nOPENAI_API_KEY=\nLOG_LEVEL=loud\nSTRAY=1\nPORT=80\n")
    report = check()
    kinds = {(i.kind, i.key) for i in report.issues}
    assert ("invalid", "DATABASE_URL") in kinds
    assert ("empty", "OPENAI_API_KEY") in kinds
    assert ("invalid", "LOG_LEVEL") in kinds
    assert ("extra", "STRAY") in kinds
    assert ("duplicate", "PORT") in kinds
    assert ("invalid", "PORT") not in kinds  # last duplicate (80) wins
    assert not report.ok


def test_check_passes_and_strict_mode(project):
    (project / ".env").write_text("PORT=8080\nDATABASE_URL=postgres://u@localhost/db\nOPENAI_API_KEY=abc\nEXTRA=1\n")
    assert check().ok
    assert not check(strict=True).ok


def test_check_missing_env_file(project):
    report = check()
    assert any(i.kind == "missing" and i.key == ".env" for i in report.issues)


def test_check_with_environ_only(project, monkeypatch):
    monkeypatch.setenv("PORT", "5000")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///app.db")
    monkeypatch.setenv("OPENAI_API_KEY", "abc")
    assert check(None, use_environ=True).ok


def test_check_flags_secret_in_example(project):
    (project / ".env.example").write_text(EXAMPLE + f"GITHUB_TOKEN={FAKE_GH}\n")
    (project / ".env").write_text("PORT=1\nDATABASE_URL=https://x.io\nOPENAI_API_KEY=a\nGITHUB_TOKEN=a\n")
    report = check()
    assert any(i.kind == "secret" for i in report.errors)
    assert FAKE_GH not in json.dumps(report.to_dict())  # never echoes the secret


# ---------- load ----------


def test_load_returns_typed_config(project, monkeypatch):
    (project / ".env").write_text("PORT=8080\nDATABASE_URL=postgres://u@h/db\nOPENAI_API_KEY=abc\nDEBUG=yes\n")
    cfg = load()
    assert cfg.PORT == 8080 and cfg.DEBUG is True
    assert cfg.LOG_LEVEL == "info" and cfg.TIMEOUT == 2.5  # optional defaults from example
    assert os.environ["OPENAI_API_KEY"] == "abc"


def test_load_environ_overrides_file(project, monkeypatch):
    (project / ".env").write_text("PORT=8080\nDATABASE_URL=postgres://u@h/db\nOPENAI_API_KEY=abc\n")
    monkeypatch.setenv("PORT", "9090")
    assert load(export=False).PORT == 9090


def test_load_raises_with_all_problems(project):
    (project / ".env").write_text("PORT=abc\n")
    with pytest.raises(EnvsureError) as exc:
        load(export=False)
    keys = {i.key for i in exc.value.report.errors}
    assert keys == {"PORT", "DATABASE_URL", "OPENAI_API_KEY"}


# ---------- sync ----------


def test_sync_adds_blanked_keys_and_guesses_types(project):
    (project / ".env").write_text(
        "PORT=1\nDATABASE_URL=postgres://u:pw@h/db\nOPENAI_API_KEY="
        + FAKE_OPENAI
        + "\n# Redis cache\nREDIS_URL=redis://localhost:6379\nWORKERS=4\nSECRET=hunter2\n"
    )
    result = sync()
    text = (project / ".env.example").read_text()
    assert result.added == ["REDIS_URL", "WORKERS", "SECRET"]
    assert "REDIS_URL=  # [url]" in text and "WORKERS=  # [int]" in text and "SECRET=\n" in text
    assert "# Redis cache" in text
    assert "hunter2" not in text and FAKE_OPENAI not in text
    assert text.startswith(EXAMPLE.rstrip("\n"))  # existing content untouched
    assert not sync().changed  # idempotent


def test_sync_prune_and_check_mode(project):
    (project / ".env").write_text("PORT=1\n")
    result = sync(prune=True, write=False)
    assert set(result.removed) == {"DEBUG", "DATABASE_URL", "LOG_LEVEL", "OPENAI_API_KEY", "TIMEOUT"}
    assert (project / ".env.example").read_text() == EXAMPLE  # write=False


# ---------- secrets ----------


def test_scan_detects_common_tokens_and_masks():
    text = f"a={FAKE_GH}\nb={FAKE_OPENAI}\nc={FAKE_ANTHROPIC}\nd={FAKE_AWS}\ne=postgres://admin:S3cretPw@db/x\n"
    findings = scan_text(text)
    assert [f.kind for f in findings] == [
        "GitHub token",
        "OpenAI API key",
        "Anthropic API key",
        "AWS access key ID",
        "Password in URL",
    ]
    assert all("*" in f.masked for f in findings)


def test_scan_ignores_placeholders_and_marked_lines():
    text = (
        "OPENAI_API_KEY=sk-your-openai-key-goes-here-xxxxx\n"
        "DB=postgres://user:${DB_PASSWORD}@db/x\n"
        f"T={FAKE_GH}  # envsure: ignore\n"
    )
    assert scan_text(text) == []


# ---------- cli ----------


def test_cli_check_json_and_exit_codes(project, capsys):
    (project / ".env").write_text("PORT=8080\nDATABASE_URL=https://db.io\nOPENAI_API_KEY=a\n")
    assert main(["check", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    (project / ".env").write_text("PORT=nope\n")
    assert main(["check"]) == 1


def test_cli_sync_check_and_scan(project, capsys):
    (project / ".env").write_text("PORT=1\nNEW_KEY=x\n")
    assert main(["sync", "--check"]) == 1
    assert main(["sync"]) == 0
    assert main(["sync", "--check"]) == 0
    (project / "leak.py").write_text(f'TOKEN = "{FAKE_GH}"\n')
    assert main(["scan", "."]) == 1
    assert FAKE_GH not in capsys.readouterr().out


def test_cli_bad_schema_exit_2(project):
    (project / ".env.example").write_text("A=1 # [nope]\n")
    assert main(["check"]) == 2

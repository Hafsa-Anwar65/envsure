# envsure

[![CI](https://github.com/Hafsa-Anwar65/envsure/actions/workflows/ci.yml/badge.svg)](https://github.com/Hafsa-Anwar65/envsure/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Keep your `.env` files honest.** envsure validates environment variables against your `.env.example`, keeps that example in sync as you add keys, and stops leaked API keys before they reach GitHub.

Every team hits the same three problems:

- 😩 "It works on my machine" — a teammate pulls your branch and the app crashes on a variable nobody told them about.
- 🕳️ `.env.example` slowly drifts out of date until nobody trusts it.
- 🔑 Someone pastes a real `sk-...` key into `.env.example` or a config file and pushes it.

envsure fixes all three with one zero-dependency tool you can run locally, in pre-commit, and in CI.

## Install

```bash
pip install git+https://github.com/Hafsa-Anwar65/envsure.git
```

or with Docker (GitHub Packages):

```bash
docker run --rm -v "$PWD:/work" ghcr.io/hafsa-anwar65/envsure check
```

## 1. Turn `.env.example` into a schema

Add optional `[annotations]` to inline comments. Everything else stays a normal `.env.example`.

```bash
# Port the API listens on
PORT=8000                 # [port]
DEBUG=false               # [bool, optional]
DATABASE_URL=             # [url] postgres connection string
OPENAI_API_KEY=           # get one at platform.openai.com
LOG_LEVEL=info            # [choice=debug|info|warning|error, optional]
ADMIN_EMAIL=              # [email, optional]
FEATURE_FLAGS={}          # [json, optional]
```

| Annotation | Meaning |
|---|---|
| `str` *(default)* `int` `float` `bool` `port` `url` `email` `json` | value type |
| `optional` | may be missing; falls back to the value in `.env.example` |
| `required` *(default)* | must be set and non-empty |
| `choice=a\|b\|c` | must be one of the listed values |

Text after the brackets (or a comment on the line above) becomes the description shown in error messages.

## 2. `envsure check`

```console
$ envsure check
ERROR   invalid   PORT: must be a port between 1 and 65535 (got '99999')
ERROR   empty     OPENAI_API_KEY: is empty — get one at platform.openai.com
ERROR   missing   DATABASE_URL: not set — postgres connection string
WARNING extra     STRIPE_KEY: not documented in .env.example
✘ 7 keys checked, 3 error(s), 1 warning(s)
```

| Flag | Use it for |
|---|---|
| `--strict` | undocumented keys become errors |
| `--environ` | also read the process environment |
| `--no-file` | validate only the process environment (CI, Docker, Kubernetes) |
| `--json` | machine-readable output |
| `--env`, `--example` | custom paths |

Exit codes: `0` OK, `1` problems found, `2` bad input (unparseable file, unknown annotation).

## 3. `envsure sync`

Added a key to `.env`? Copy it to `.env.example` **with the value blanked** and a guessed type:

```console
$ envsure sync
Added to .env.example (values blanked): REDIS_URL, WORKERS
```

```bash
REDIS_URL=  # [url]
WORKERS=  # [int]
```

Existing lines are never rewritten. `--prune` removes keys you deleted from `.env`; `--check` writes nothing and exits `1` if the example is stale — perfect for pre-commit.

## 4. `envsure scan`

```console
$ envsure scan .
config/settings.py:12  OpenAI API key  sk-p************a1B2
.env.example:9  Password in URL  S3cr************Pw99
✘ 2 possible secret(s) found. Add `envsure: ignore` to a line to silence a false positive.
```

Detects OpenAI, Anthropic, GitHub, AWS, Google, Slack, Stripe, Hugging Face and Groq keys, JWTs, private keys and passwords inside connection URLs. Secrets are always masked in output. Obvious placeholders (`sk-your-key-here`, `xxxx`, `<token>`, `${DB_PASSWORD}`) are skipped. `check` also scans `.env.example` automatically.

## Use it in Python

```python
from envsure import load

cfg = load()            # validates .env against .env.example, returns typed values
cfg.PORT                # 8000  (int)
cfg.DEBUG               # False (bool)
cfg["DATABASE_URL"]     # str
```

If anything is wrong, `load()` raises `envsure.EnvsureError` listing **every** problem at once instead of failing on the first one. Values already in `os.environ` win over the file (12-factor style); pass `environ_wins=False` to flip that. Keys from the file are exported to `os.environ` for libraries that read it directly (`export=False` to disable).

## pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/Hafsa-Anwar65/envsure
    rev: v0.1.0
    hooks:
      - id: envsure-scan   # block commits containing secrets
      - id: envsure-sync   # fail if .env.example is missing keys from .env
```

## GitHub Actions

```yaml
- uses: Hafsa-Anwar65/envsure@v0.1.0
  with:
    command: scan

- uses: Hafsa-Anwar65/envsure@v0.1.0
  env:
    DATABASE_URL: ${{ secrets.DATABASE_URL }}
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  with:
    command: check
    args: --strict
```

## Development

```bash
git clone https://github.com/Hafsa-Anwar65/envsure && cd envsure
pip install -e ".[dev]"
pytest && ruff check src tests
```

Releases: push a tag like `v0.1.0`. The release workflow attaches the wheel to the GitHub release and publishes the Docker image to `ghcr.io/hafsa-anwar65/envsure`.

## License

MIT © Hafsa Anwar

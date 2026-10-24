"""envsure — keep .env files honest: validate, sync and scan for leaked secrets."""

__version__ = "0.1.0"

from .core import Config, EnvsureError, Issue, Report, check, load, sync
from .secrets import scan_paths, scan_text

__all__ = ["Config", "EnvsureError", "Issue", "Report", "__version__", "check", "load", "scan_paths", "scan_text", "sync"]

"""Version as ``<major>.<minor>.<commit count>``.

The last segment is the number of commits reachable from ``HEAD``, read from git at import time.
Outside a git checkout (e.g. an installed wheel) it falls back to the packaged version, which is
the static ``version`` in pyproject.toml.
"""

from __future__ import annotations

import subprocess
from importlib import metadata
from pathlib import Path

BASE_VERSION = "0.1"


def _commit_count() -> int | None:
    try:
        completed = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return int(completed.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def get_version() -> str:
    count = _commit_count()
    if count is not None:
        return f"{BASE_VERSION}.{count}"
    try:
        return metadata.version("pallet-builder")
    except metadata.PackageNotFoundError:
        return f"{BASE_VERSION}.0"

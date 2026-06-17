from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from typing import Any, Dict


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _run_git(args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=_repo_root(),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=2,
    )
    return proc.stdout.strip()


def _git_version_info() -> Dict[str, Any] | None:
    try:
        short_commit = _run_git(["rev-parse", "--short=12", "HEAD"])
    except Exception:
        return None
    if not short_commit:
        return None
    try:
        branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    except Exception:
        branch = ""
    try:
        dirty = bool(_run_git(["status", "--porcelain"]))
    except Exception:
        dirty = False
    version = short_commit + ("-dirty" if dirty else "")
    return {
        "version": version,
        "source": "git",
        "short_commit": short_commit,
        "branch": branch,
        "dirty": dirty,
    }


def _generated_version_info() -> Dict[str, Any] | None:
    try:
        from . import build_info  # type: ignore
    except Exception:
        return None
    raw = getattr(build_info, "BUILD_INFO", None)
    if not isinstance(raw, dict):
        return None
    version = str(raw.get("version") or raw.get("short_commit") or "").strip()
    if not version:
        return None
    return {
        "version": version,
        "source": "generated",
        "short_commit": str(raw.get("short_commit") or "").strip(),
        "branch": str(raw.get("branch") or "").strip(),
        "dirty": bool(raw.get("dirty") or False),
        "build_time": str(raw.get("build_time") or "").strip(),
    }


@lru_cache(maxsize=1)
def app_version_info() -> Dict[str, Any]:
    info = _git_version_info() or _generated_version_info()
    if info:
        return info
    return {
        "version": "dev",
        "source": "vdev",
        "short_commit": "",
        "branch": "",
        "dirty": False,
    }


def app_version() -> str:
    return str(app_version_info().get("version") or "dev")

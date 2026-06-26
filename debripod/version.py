from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache
from typing import Any, Dict, List

BASE_NUMERIC_VERSION = 194
VERSION_FLOOR_COMMIT = "ff2b1d13748ede3d1cce9956d710545d8ec5ae76"


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _run_git(args: List[str]) -> str:
    root = _repo_root()
    proc = subprocess.run(
        ["git", "-c", f"safe.directory={root}", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=4,
    )
    return proc.stdout.strip()


def _changed_files_for_commit(commit: str) -> List[str]:
    out = _run_git(["diff-tree", "--no-commit-id", "--name-only", "-r", commit])
    return [line.strip() for line in out.splitlines() if line.strip()]


def _is_readme_or_gitignore(path: str) -> bool:
    norm = str(path or "").replace("\\", "/").strip().lower()
    if not norm:
        return False
    base = norm.rsplit("/", 1)[-1]
    return base == ".gitignore" or base == "readme" or base.startswith("readme.")


def _is_merge_commit(commit: str) -> bool:
    line = _run_git(["rev-list", "--parents", "-n", "1", commit])
    return len([part for part in line.split() if part]) > 2


def _is_pull_request_merge_subject(commit: str) -> bool:
    try:
        subject = _run_git(["show", "-s", "--format=%s", commit]).lower()
    except Exception:
        return False
    return subject.startswith("merge pull request ") or subject.startswith("merged pull request ")


def _qualifies_for_numeric_version(commit: str) -> bool:
    try:
      if _is_merge_commit(commit) or _is_pull_request_merge_subject(commit):
          return False
      files = _changed_files_for_commit(commit)
    except Exception:
      return False
    if not files:
        return False
    return not all(_is_readme_or_gitignore(path) for path in files)


def _git_version_info() -> Dict[str, Any] | None:
    try:
        _run_git(["merge-base", "--is-ancestor", VERSION_FLOOR_COMMIT, "HEAD"])
        full_commit = _run_git(["rev-parse", "HEAD"])
        short_commit = _run_git(["rev-parse", "--short=7", "HEAD"])
        commits = _run_git(["rev-list", "--first-parent", f"{VERSION_FLOOR_COMMIT}..HEAD"]).splitlines()
    except Exception:
        return None

    qualifying = 0
    for commit in commits:
        if commit and _qualifies_for_numeric_version(commit):
            qualifying += 1

    try:
        branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    except Exception:
        branch = ""
    try:
        dirty = bool(_run_git(["status", "--porcelain"]))
    except Exception:
        dirty = False

    numeric_version = BASE_NUMERIC_VERSION + qualifying
    display_version = f"v{numeric_version}"
    return {
        "version": str(numeric_version),
        "display_version": display_version,
        "numeric_version": numeric_version,
        "source": "git",
        "short_commit": short_commit,
        "full_commit": full_commit,
        "branch": branch,
        "dirty": dirty,
        "qualifying_commit_count": qualifying,
        "version_floor_commit": VERSION_FLOOR_COMMIT,
    }


def _generated_version_info() -> Dict[str, Any] | None:
    raw: Dict[str, Any] | None = None
    json_path = os.path.join(os.path.dirname(__file__), "build_info.json")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            raw = loaded
    except Exception:
        raw = None

    if raw is None:
        try:
            from . import build_info  # type: ignore
            loaded = getattr(build_info, "BUILD_INFO", None)
            if isinstance(loaded, dict):
                raw = loaded
        except Exception:
            raw = None

    if not isinstance(raw, dict):
        return None

    display_version = str(raw.get("display_version") or "").strip()
    numeric_version = raw.get("numeric_version")
    version = str(raw.get("version") or "").strip()
    if not version and numeric_version is not None:
        version = str(numeric_version)
    if not display_version and version:
        display_version = version if version.startswith("v") else "v" + version
    if not version and not display_version:
        return None

    return {
        "version": version or display_version.lstrip("v"),
        "display_version": display_version or ("v" + version),
        "numeric_version": numeric_version,
        "source": "generated",
        "short_commit": str(raw.get("short_commit") or "").strip(),
        "full_commit": str(raw.get("full_commit") or "").strip(),
        "branch": str(raw.get("branch") or "").strip(),
        "dirty": bool(raw.get("dirty") or False),
        "build_time": str(raw.get("build_time") or "").strip(),
        "qualifying_commit_count": raw.get("qualifying_commit_count"),
        "version_floor_commit": str(raw.get("version_floor_commit") or VERSION_FLOOR_COMMIT),
    }


@lru_cache(maxsize=1)
def app_version_info() -> Dict[str, Any]:
    info = _git_version_info() or _generated_version_info()
    if info:
        return info
    return {
        "version": "dev",
        "display_version": "vdev",
        "numeric_version": None,
        "source": "vdev",
        "short_commit": "",
        "full_commit": "",
        "branch": "",
        "dirty": False,
        "qualifying_commit_count": None,
        "version_floor_commit": VERSION_FLOOR_COMMIT,
    }


def app_version() -> str:
    return str(app_version_info().get("version") or "dev")

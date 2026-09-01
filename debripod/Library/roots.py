from __future__ import annotations

import os
import re
from typing import Any, Callable, List, Optional, Tuple

from ..utils import sha1_text
from .library_db import associated_library_roots, replace_user_library_roots, user_has_library_root, user_library_roots

_library_folders_provider: Callable[[], List[Any]] = lambda: []
_download_folders_provider: Callable[[], dict[str, str]] = lambda: {}
LIBRARY_ALL_ROOT_ID = "__all__"


def configure_library_roots(
    library_folders_provider: Callable[[], List[Any]],
    download_folders_provider: Optional[Callable[[], dict[str, str]]] = None,
) -> None:
    global _library_folders_provider, _download_folders_provider
    _library_folders_provider = library_folders_provider
    if download_folders_provider is not None:
        _download_folders_provider = download_folders_provider


def _parse_library_folder_spec(spec: Any) -> Optional[Tuple[str, str, str]]:
    if not isinstance(spec, dict):
        return None
    path = str(spec.get("path") or "").strip()
    if not path:
        return None
    path = (path or "").strip().strip('"').strip("'")
    if not path or not os.path.isabs(path):
        return None

    ap = os.path.realpath(os.path.abspath(path))
    name = os.path.basename(ap.rstrip("\\/")) or ap
    return name, ap, "metadata"


def root_id_for_path(path: str) -> str:
    return sha1_text(os.path.realpath(os.path.abspath(str(path or ""))))


def _settings_root_specs(settings: dict[str, Any]) -> list[dict[str, Any]]:
    parsed: list[tuple[str, str, str, str]] = []
    for spec in (settings.get("LIBRARY_FOLDERS") or []):
        p = _parse_library_folder_spec(spec)
        if not p:
            continue
        name, ap, mode = p
        parsed.append((name, ap, mode, "library"))
    labels = {"debrid": "Debrid", "soulseek": "Soulseek", "youtube": "YouTube"}
    for source, key in (("debrid", "DOWNLOAD_DIR"), ("soulseek", "SOULSEEK_DOWNLOAD_DIR"), ("youtube", "YOUTUBE_DOWNLOAD_DIR")):
        path = settings.get(key)
        clean = str(path or "").strip()
        if not clean or not os.path.isabs(clean):
            continue
        ap = os.path.realpath(os.path.abspath(clean))
        parsed.append((labels.get(source, os.path.basename(ap.rstrip("\\/")) or ap), ap, "metadata", source))

    out: list[dict[str, Any]] = []
    seen = set()
    for name, ap, mode, source in parsed:
        key = os.path.normcase(ap)
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": root_id_for_path(ap), "name": name, "path": ap, "mode": mode, "source": source})
    return out


def sync_user_roots(user_id: str, settings: dict[str, Any]) -> list[str]:
    """Persist one user's root memberships and preserve shared physical IDs."""
    return replace_user_library_roots(str(user_id or ""), _settings_root_specs(settings))


def roots(user_id: str | None = None) -> List[Tuple[str, str, str, str]]:
    rows = user_library_roots(str(user_id)) if user_id is not None else associated_library_roots()
    return [
        (
            str(row.get("root_id") or ""),
            str(row.get("display_name") or row.get("root_abs") or ""),
            str(row.get("root_abs") or ""),
            str(row.get("mode") or "metadata"),
        )
        for row in rows
    ]


def root_objects(user_id: str | None = None) -> List[dict]:
    rows = user_library_roots(str(user_id)) if user_id is not None else associated_library_roots()
    return [
        {
            "id": str(row.get("root_id") or ""),
            "name": str(row.get("display_name") or row.get("root_abs") or ""),
            "path": str(row.get("root_abs") or ""),
            "mode": str(row.get("mode") or "metadata"),
            "source": str(row.get("source") or "library"),
        }
        for row in rows
    ]


def source_origin_for_path(abs_path: str, user_id: str | None = None) -> str:
    candidate = os.path.realpath(os.path.abspath(str(abs_path or "")))
    matches: list[tuple[int, str]] = []
    for root in root_objects(user_id):
        root_abs = str(root.get("path") or "")
        try:
            if os.path.commonpath([root_abs, candidate]) == root_abs:
                matches.append((len(root_abs), str(root.get("source") or "library")))
        except Exception:
            continue
    return max(matches, default=(0, "library"))[1]


def root_by_id(root_id: str, user_id: str | None = None) -> Optional[Tuple[str, str, str, str]]:
    if user_id is not None and not user_has_library_root(str(user_id), root_id):
        return None
    for rid, name, ap, mode in roots(user_id):
        if rid == str(root_id or ""):
            return rid, name, ap, mode
    return None


def safe_path_join(root_abs: str, rel: str) -> str:
    rel = rel or ""
    rel = rel.replace("\\", "/")
    if "\x00" in rel:
        raise ValueError("Invalid path")
    if os.path.isabs(rel) or re.match(r"^[A-Za-z]:", rel) or rel.startswith("//"):
        raise ValueError("Invalid path")
    parts = [p for p in rel.split("/") if p]
    reserved = {"con", "prn", "aux", "nul", "clock$"}
    reserved.update({f"com{i}" for i in range(1, 10)})
    reserved.update({f"lpt{i}" for i in range(1, 10)})
    for part in parts:
        clean = part.strip().rstrip(". ").lower()
        if part in {".", ".."} or clean in reserved:
            raise ValueError("Invalid path")
    rel = rel.lstrip("/")
    joined = os.path.realpath(os.path.abspath(os.path.join(root_abs, rel.replace("/", os.sep))))
    root_abs = os.path.realpath(os.path.abspath(root_abs))
    try:
        common = os.path.commonpath([root_abs, joined])
    except Exception:
        raise ValueError("Invalid path")
    if common != root_abs:
        raise ValueError("Path escapes root")
    return joined

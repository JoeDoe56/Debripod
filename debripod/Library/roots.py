from __future__ import annotations

import os
import re
from typing import Any, Callable, List, Optional, Tuple

from ..utils import sha1_text

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

    ap = os.path.abspath(path)
    name = os.path.basename(ap.rstrip("\\/")) or ap
    return name, ap, "metadata"


def roots() -> List[Tuple[str, str, str, str]]:
    parsed: List[Tuple[str, str, str]] = []

    for spec in (_library_folders_provider() or []):
        p = _parse_library_folder_spec(spec)
        if not p:
            continue
        name, ap, mode = p
        parsed.append((name, ap, mode))
    labels = {"debrid": "Debrid", "soulseek": "Soulseek", "youtube": "YouTube"}
    for source, path in (_download_folders_provider() or {}).items():
        clean = str(path or "").strip()
        if not clean or not os.path.isabs(clean):
            continue
        ap = os.path.abspath(clean)
        parsed.append((labels.get(str(source), os.path.basename(ap.rstrip("\\/")) or ap), ap, "metadata"))

    out: List[Tuple[str, str, str, str]] = []
    seen = set()
    for name, ap, mode in parsed:
        ap2 = os.path.abspath(ap)
        key = os.path.normcase(os.path.realpath(ap2))
        if key in seen:
            continue
        seen.add(key)
        rid = sha1_text(ap2)
        out.append((rid, name, ap2, mode))
    return out


def root_objects() -> List[dict]:
    download_roots = {
        os.path.normcase(os.path.realpath(os.path.abspath(str(path)))): str(source)
        for source, path in (_download_folders_provider() or {}).items()
        if str(path or "").strip() and os.path.isabs(str(path))
    }
    out = []
    for rid, name, ap, mode in roots():
        source = download_roots.get(os.path.normcase(os.path.realpath(ap)), "library")
        out.append({"id": rid, "name": name, "path": ap, "mode": mode, "source": source})
    return out


def source_origin_for_path(abs_path: str) -> str:
    candidate = os.path.realpath(os.path.abspath(str(abs_path or "")))
    matches: list[tuple[int, str]] = []
    for source, root in (_download_folders_provider() or {}).items():
        clean = str(root or "").strip()
        if not clean:
            continue
        root_abs = os.path.realpath(os.path.abspath(clean))
        try:
            if os.path.commonpath([root_abs, candidate]) == root_abs:
                matches.append((len(root_abs), str(source)))
        except Exception:
            continue
    return max(matches, default=(0, "library"))[1]


def root_by_id(root_id: str) -> Optional[Tuple[str, str, str, str]]:
    for rid, name, ap, mode in roots():
        if rid == root_id:
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

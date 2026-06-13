from __future__ import annotations

import os
import re
from typing import Callable, List, Optional, Tuple

from ..utils import sha1_text

_library_folders_provider: Callable[[], List[str]] = lambda: []


def configure_library_roots(library_folders_provider: Callable[[], List[str]]) -> None:
    global _library_folders_provider
    _library_folders_provider = library_folders_provider


def _parse_library_folder_spec(spec: str) -> Optional[Tuple[str, str, str]]:
    spec = (spec or "").strip()
    if not spec:
        return None

    mode = None
    path = spec

    if ":" in spec:
        p, suf = spec.rsplit(":", 1)
        suf_l = (suf or "").strip().lower()
        if suf_l in ("meta", "metadata", "m"):
            mode = "metadata"
            path = p
        elif suf_l in ("list", "folders", "folder", "l"):
            mode = "folders"
            path = p

    if mode is None:
        mode = "folders"

    path = (path or "").strip().strip('"').strip("'")
    if not path or not os.path.isabs(path):
        return None

    ap = os.path.abspath(path)
    name = os.path.basename(ap.rstrip("\\/")) or ap
    return name, ap, mode


def roots() -> List[Tuple[str, str, str, str]]:
    parsed: List[Tuple[str, str, str]] = []

    for spec in (_library_folders_provider() or []):
        p = _parse_library_folder_spec(spec)
        if not p:
            continue
        name, ap, mode = p
        parsed.append((name, ap, mode))

    out: List[Tuple[str, str, str, str]] = []
    seen = set()
    for name, ap, mode in parsed:
        ap2 = os.path.abspath(ap)
        if ap2 in seen:
            continue
        seen.add(ap2)
        rid = sha1_text(ap2)
        out.append((rid, name, ap2, mode))
    return out


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

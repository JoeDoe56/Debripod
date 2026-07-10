from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class DebridProviderSpec:
    id: str
    label: str
    token_setting_key: str
    base_setting_key: str


@dataclass
class DebridFile:
    file_id: str
    path: str
    name: str
    bytes: int = 0
    provider_link: str = ""
    provider_task_id: str = ""
    provider_file_id: str = ""
    media: str = ""
    ext: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DebridPreview:
    provider: str
    provider_task_id: str
    title: str = ""
    status: str = ""
    files: List[DebridFile] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
    ready: bool = False


@dataclass
class DebridResolvedLink:
    url: str
    filename: str = ""
    size: int = 0
    mime: str = ""
    expires_at: Optional[float] = None
    requires_refresh: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _json_safe(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


@dataclass(slots=True)
class SearchFile:
    file_id: str = ""
    name: str = ""
    title: str = ""
    path: str = ""
    size: int = 0
    duration: float = 0.0
    media: str = ""
    stream_available: bool = False
    download_available: bool = False
    provider_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(slots=True)
class SearchResult:
    result_id: str
    provider_group: str
    source: str
    source_label: str
    kind: str
    kind_label: str
    title: str
    subtitle: str = ""
    artist: str = ""
    album: str = ""
    year: str = ""
    duration: float = 0.0
    thumbnail: str = ""
    canonical_url: str = ""
    stable_source_id: str = ""
    search_blob: str = ""
    filter_values: dict[str, list[str]] = field(default_factory=lambda: {
        "sources": [], "types": [], "indexers": [], "media": [],
    })
    match_confidence: float = 0.0
    rank_score: float = 0.0
    browse_available: bool = False
    stream_available: bool = False
    download_available: bool = False
    files_loaded: bool = False
    file_count: int = 0
    size: int = 0
    files: list[SearchFile | dict[str, Any]] = field(default_factory=list)
    provider_data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        missing = [name for name in ("result_id", "source", "kind", "title") if not str(getattr(self, name, "") or "").strip()]
        if missing:
            raise ValueError("SearchResult missing required field(s): " + ", ".join(missing))
        self.provider_group = str(self.provider_group or "").strip().lower()
        self.source = str(self.source or "").strip().lower()
        self.kind = str(self.kind or "").strip().lower()
        self.filter_values = {
            key: list(dict.fromkeys(str(value) for value in (self.filter_values.get(key) or []) if str(value)))
            for key in ("sources", "types", "indexers", "media")
        }
        if not isinstance(self.provider_data, dict):
            raise TypeError("provider_data must be a mapping")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SearchResult":
        known = set(cls.__dataclass_fields__)
        unknown = set(value) - known
        if unknown:
            raise ValueError("Unknown top-level search result field(s): " + ", ".join(sorted(unknown)))
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(slots=True)
class ProviderSearchResponse:
    provider_group: str
    source_status: Any = field(default_factory=dict)
    results: list[SearchResult | dict[str, Any]] = field(default_factory=list)
    error: str = ""
    duration_ms: int = 0
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_group": self.provider_group,
            "source_status": _json_safe(self.source_status),
            "results": [_json_safe(item) for item in self.results],
            "error": self.error,
            "duration_ms": int(self.duration_ms or 0),
            "cached": bool(self.cached),
        }

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import ProviderSearchResponse


@dataclass(slots=True)
class SearchContext:
    username: str
    query: str
    normalized_query: str
    intent: dict[str, float]
    settings: dict[str, Any]
    search_id: str
    cancellation_event: threading.Event = field(default_factory=threading.Event)
    debug: bool = False


class SearchProvider(Protocol):
    provider_group: str

    def search(self, query: str, context: SearchContext) -> ProviderSearchResponse: ...

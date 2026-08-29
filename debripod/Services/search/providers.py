from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol

from .models import ProviderSearchResponse


@dataclass(slots=True)
class SearchContext:
    username: str
    query: str
    normalized_query: str
    intent: dict[str, float]
    settings: dict[str, Any]
    search_id: str
    debug: bool = False


class SearchProvider(Protocol):
    provider_group: str

    def search_stream(
        self,
        query: str,
        context: SearchContext,
    ) -> AsyncIterator[ProviderSearchResponse]: ...

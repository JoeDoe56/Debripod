from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterable

from ...Library.search_ranker import rank_combined_results
from .dedup import deduplicate_torrents, deduplicate_youtube
from .models import ProviderSearchResponse, SearchResult
from .providers import SearchContext, SearchProvider
from .relevance import assess_match, build_search_blob


def _plain(result: Any) -> dict[str, Any]:
    return result.to_dict() if hasattr(result, "to_dict") else dict(result)


def normalize_result(result: Any) -> dict[str, Any]:
    raw = _plain(result)
    # Keep strict schema validation without a dataclass -> asdict deep-copy on
    # every row. That conversion is measurable at 30,000 results.
    known = set(SearchResult.__dataclass_fields__)
    unknown = set(raw) - known
    if unknown:
        raise ValueError("Unknown top-level search result field(s): " + ", ".join(sorted(unknown)))
    missing = [key for key in ("result_id", "source", "kind", "title") if not str(raw.get(key) or "").strip()]
    if missing:
        raise ValueError("SearchResult missing required field(s): " + ", ".join(missing))
    if not isinstance(raw.get("provider_data", {}), dict):
        raise TypeError("provider_data must be a mapping")
    validated = {
        "result_id": "", "provider_group": "", "source": "", "source_label": "", "kind": "", "kind_label": "", "title": "",
        "subtitle": "", "artist": "", "album": "", "year": "", "duration": 0.0, "thumbnail": "", "canonical_url": "",
        "stable_source_id": "", "search_blob": "", "filter_values": {"sources": [], "types": [], "indexers": [], "media": []},
        "match_confidence": 0.0, "rank_score": 0.0, "browse_available": False, "stream_available": False,
        "download_available": False, "files_loaded": False, "file_count": 0, "size": 0, "files": [], "provider_data": {},
    }
    validated.update(raw)
    validated["provider_group"] = str(validated["provider_group"] or "").strip().lower()
    validated["source"] = str(validated["source"] or "").strip().lower()
    validated["kind"] = str(validated["kind"] or "").strip().lower()
    validated["search_blob"] = build_search_blob(validated)
    provider = validated.get("provider_data") or {}
    media = ""
    if validated["kind"] in {"song", "album", "artist", "music_playlist", "music_video"}:
        media = "music"
    elif validated["kind"] in {"movie", "show", "season", "episode", "video"}:
        media = "video"
    indexers = list(provider.get("indexer_labels") or []) if validated["source"] == "torrent" else []
    validated["filter_values"] = {
        "sources": [validated["source_label"]],
        "types": [validated["kind_label"]],
        "indexers": list(dict.fromkeys(str(value) for value in indexers if str(value))),
        "media": [media] if media else [],
    }
    return validated


class SearchPipeline:
    def __init__(self, providers: Iterable[SearchProvider], *, cache: Any = None, max_workers: int | None = None):
        self.providers = list(providers)
        self.cache = cache
        self.max_workers = max_workers or max(1, len(self.providers))

    def _cache_set(self, context: SearchContext, payload: dict[str, Any]) -> None:
        if self.cache is None:
            return
        safe_payload = {
            "query": context.query,
            "search_id": context.search_id,
            "results": payload.get("results", []),
            "provider_status": payload.get("provider_status", []),
        }
        if hasattr(self.cache, "set"):
            self.cache.set(context.search_id, safe_payload)
        elif callable(self.cache):
            self.cache(context.search_id, safe_payload)

    def search_stream(self, query: str, context: SearchContext):
        yield {"event": "start", "search_id": context.search_id, "query": query}
        retained: list[dict[str, Any]] = []
        statuses: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="debripod-search") as executor:
            futures = {executor.submit(provider.search, query, context): provider for provider in self.providers}
            for future in as_completed(futures):
                provider = futures[future]
                started = time.monotonic()
                try:
                    response = future.result()
                    if not isinstance(response, ProviderSearchResponse):
                        response = ProviderSearchResponse(**dict(response))
                except Exception as exc:
                    response = ProviderSearchResponse(
                        provider_group=provider.provider_group,
                        source_status={"status": "error"},
                        error=str(exc),
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
                normalized: list[dict[str, Any]] = []
                invalid_errors: list[str] = []
                for row in response.results:
                    try:
                        normalized.append(normalize_result(row))
                    except Exception as exc:
                        invalid_errors.append(str(exc))
                if response.provider_group == "ytdlp":
                    normalized = deduplicate_youtube(normalized)
                if response.provider_group == "torrents":
                    normalized = deduplicate_torrents(normalized)
                filtered: list[dict[str, Any]] = []
                for row in normalized:
                    assessment = assess_match(query, row)
                    row["match_confidence"] = assessment.confidence
                    if not assessment.unrelated:
                        filtered.append(row)
                retained.extend(filtered)
                status = {
                    "provider_group": response.provider_group,
                    "source_status": response.source_status,
                    "error": response.error or ("; ".join(invalid_errors) if invalid_errors else ""),
                    "duration_ms": response.duration_ms,
                    "cached": response.cached,
                    "result_count": len(filtered),
                }
                statuses.append(status)
                yield {"event": "source", "search_id": context.search_id, **status, "results": filtered}
        ranked = rank_combined_results(retained, query, intent=context.intent)
        payload = {"event": "done", "search_id": context.search_id, "query": query, "results": ranked, "provider_status": statuses}
        self._cache_set(context, payload)
        yield payload

    def search_once(self, query: str, context: SearchContext) -> dict[str, Any]:
        final: dict[str, Any] = {}
        for event in self.search_stream(query, context):
            if event.get("event") == "done":
                final = event
        return final


def search_stream(query: str, context: SearchContext, providers: Iterable[SearchProvider] | None = None, *, pipeline: SearchPipeline | None = None):
    active = pipeline or SearchPipeline(providers or [])
    yield from active.search_stream(query, context)


def search_once(query: str, context: SearchContext, providers: Iterable[SearchProvider] | None = None, *, pipeline: SearchPipeline | None = None) -> dict[str, Any]:
    return (pipeline or SearchPipeline(providers or [])).search_once(query, context)

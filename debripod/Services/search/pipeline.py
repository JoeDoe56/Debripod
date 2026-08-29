from __future__ import annotations

import asyncio
import copy
import inspect
import time
from typing import Any, AsyncIterator, Iterable

from ...Library.search_ranker import rank_combined_results
from ..http import HttpStatusError
from ..torrent_sources.base import SourceUnavailable
from .dedup import IncrementalDeduplicator, TorrentAccumulator
from .models import ProviderSearchResponse, SearchResult
from .providers import SearchContext, SearchProvider
from .relevance import assess_match, build_search_blob


def _plain(result: Any) -> dict[str, Any]:
    return result.to_dict() if hasattr(result, "to_dict") else dict(result)


def normalize_result(result: Any) -> dict[str, Any]:
    raw = _plain(result)
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
    indexers = list(provider.get("indexer_labels") or []) if validated["source"] in {"torrent", "local_index"} else []
    incoming_filters = validated.get("filter_values") if isinstance(validated.get("filter_values"), dict) else {}
    validated["filter_values"] = {
        "sources": list(dict.fromkeys([*(incoming_filters.get("sources") or []), validated["source_label"]])),
        "types": list(dict.fromkeys([*(incoming_filters.get("types") or []), validated["kind_label"]])),
        "indexers": list(dict.fromkeys([*(incoming_filters.get("indexers") or []), *(str(value) for value in indexers if str(value))])),
        "media": list(dict.fromkeys([*(incoming_filters.get("media") or []), *([media] if media else [])])),
    }
    return validated


async def _provider_responses(provider: Any, query: str, context: SearchContext) -> AsyncIterator[ProviderSearchResponse]:
    stream = getattr(provider, "search_stream", None)
    if callable(stream):
        iterator = stream(query, context)
        if hasattr(iterator, "__aiter__"):
            async for response in iterator:
                yield response if isinstance(response, ProviderSearchResponse) else ProviderSearchResponse(**dict(response))
            return
    value = provider.search(query, context)
    response = await value if inspect.isawaitable(value) else value
    yield response if isinstance(response, ProviderSearchResponse) else ProviderSearchResponse(**dict(response))


def _error_state(error: BaseException) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return "timeout"
    if isinstance(error, SourceUnavailable):
        return error.code
    if isinstance(error, HttpStatusError) and error.status == 429:
        return "rate_limited"
    return "error"


class SearchPipeline:
    def __init__(
        self,
        providers: Iterable[SearchProvider],
        *,
        cache: Any = None,
        torrent_accumulator_factory=TorrentAccumulator,
        max_workers: int | None = None,
    ):
        self.providers = list(providers)
        self.cache = cache
        self.torrent_accumulator_factory = torrent_accumulator_factory

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

    async def search_stream(self, query: str, context: SearchContext) -> AsyncIterator[dict[str, Any]]:
        if not str(query or "").strip():
            raise ValueError("search query is required")
        yield {"event": "start", "search_id": context.search_id, "query": query}
        queue: asyncio.Queue[tuple[str, Any, Any]] = asyncio.Queue()
        deduplicator = IncrementalDeduplicator(self.torrent_accumulator_factory)
        statuses: list[dict[str, Any]] = []
        has_local_index = any(str(getattr(provider, "provider_group", "")) == "local_index" for provider in self.providers)
        local_index_seeded = not has_local_index
        buffered_torrent_responses: list[ProviderSearchResponse] = []

        async def run_provider(provider: Any) -> None:
            started = time.monotonic()
            try:
                async for response in _provider_responses(provider, query, context):
                    await queue.put(("response", provider, response))
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                await queue.put((
                    "response",
                    provider,
                    ProviderSearchResponse(
                        provider_group=str(getattr(provider, "provider_group", "unknown")),
                        source_status={"status": _error_state(exc)},
                        error=str(exc),
                        duration_ms=int((time.monotonic() - started) * 1000),
                    ),
                ))
            finally:
                await queue.put(("done", provider, None))

        def ingest_response(response: ProviderSearchResponse) -> dict[str, Any]:
            normalized: list[dict[str, Any]] = []
            invalid_errors: list[str] = []
            for raw in response.results:
                try:
                    row = normalize_result(raw)
                    assessment = assess_match(query, row)
                    row["match_confidence"] = assessment.confidence
                    if not assessment.unrelated:
                        normalized.append(row)
                except Exception as exc:
                    invalid_errors.append(str(exc))
            upserts = [copy.deepcopy(deduplicator.ingest(row)) for row in normalized]
            source_state = "ok" if upserts else "empty"
            if response.error:
                raw_state = response.source_status.get("status") if isinstance(response.source_status, dict) else ""
                source_state = str(raw_state or "error")
            status = {
                "provider_group": response.provider_group,
                "source_id": str(response.source_status.get("source_id") or response.provider_group) if isinstance(response.source_status, dict) else response.provider_group,
                "source_label": str(response.source_status.get("source_label") or "") if isinstance(response.source_status, dict) else "",
                "source_status": response.source_status,
                "status": source_state,
                "error": response.error or ("; ".join(invalid_errors) if invalid_errors else ""),
                "duration_ms": response.duration_ms,
                "cached": response.cached,
                "result_count": len(upserts),
            }
            statuses.append(status)
            return {"event": "source", "search_id": context.search_id, **status, "results": upserts}

        tasks = [asyncio.create_task(run_provider(provider), name=f"search:{getattr(provider, 'provider_group', 'provider')}") for provider in self.providers]
        completed = 0
        try:
            while completed < len(tasks):
                message, provider, response = await queue.get()
                if message == "done":
                    completed += 1
                    if str(getattr(provider, "provider_group", "")) == "local_index" and not local_index_seeded:
                        local_index_seeded = True
                        for buffered in buffered_torrent_responses:
                            yield ingest_response(buffered)
                        buffered_torrent_responses.clear()
                    continue
                if response.provider_group == "torrents" and not local_index_seeded:
                    buffered_torrent_responses.append(response)
                    continue
                yield ingest_response(response)
                if response.provider_group == "local_index" and not local_index_seeded:
                    local_index_seeded = True
                    for buffered in buffered_torrent_responses:
                        yield ingest_response(buffered)
                    buffered_torrent_responses.clear()
            ranked = rank_combined_results(deduplicator.values(), query, intent=context.intent)
            payload = {
                "event": "done", "ok": True, "search_id": context.search_id,
                "cache_key": context.search_id, "query": query,
                "results": ranked, "result_count": len(ranked), "provider_status": statuses,
            }
            self._cache_set(context, payload)
            yield payload
        except asyncio.CancelledError:
            raise
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def search_once(self, query: str, context: SearchContext) -> dict[str, Any]:
        final: dict[str, Any] = {}
        async for event in self.search_stream(query, context):
            if event.get("event") == "done":
                final = event
        return final


async def search_stream(query: str, context: SearchContext, providers: Iterable[SearchProvider] | None = None, *, pipeline: SearchPipeline | None = None):
    active = pipeline or SearchPipeline(providers or [])
    async for event in active.search_stream(query, context):
        yield event


async def search_once(query: str, context: SearchContext, providers: Iterable[SearchProvider] | None = None, *, pipeline: SearchPipeline | None = None) -> dict[str, Any]:
    return await (pipeline or SearchPipeline(providers or [])).search_once(query, context)

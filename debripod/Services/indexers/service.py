from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from .cardigann.engine import CardigannEngine, RequestSpec
from .definition_store import DefinitionStore
from .http_client import IndexerHttpClient
from .status import IndexerStatusStore
from ..search.dedup import deduplicate_torrents
from ..search.identity import torrent_result_id
from ..search.models import ProviderSearchResponse
from ..search.relevance import assess_match


_BTIH = re.compile(r"(?:urn:btih:|btih:)([A-Za-z0-9]{32,40})", re.I)
_MAX_SEARCH_MIRRORS = 3


class IndexerService:
    provider_group = "torrents"

    def __init__(self, definition_store: DefinitionStore, *, enabled_ids: list[str] | Callable[[], list[str]], status_store: IndexerStatusStore | None = None, engine_factory: Callable[[Any], CardigannEngine] = CardigannEngine, client_factory: Callable[[str], Any] | None = None, max_concurrent: int = 6):
        self.definition_store = definition_store
        self.enabled_ids = enabled_ids
        self.status_store = status_store or IndexerStatusStore()
        self.engine_factory = engine_factory
        self.client_factory = client_factory or (lambda indexer_id: IndexerHttpClient(indexer_id, status_store=self.status_store))
        self.max_concurrent = max(1, min(6, int(max_concurrent)))

    def _enabled(self) -> set[str]:
        values = self.enabled_ids() if callable(self.enabled_ids) else self.enabled_ids
        return {str(value) for value in values or []}

    @staticmethod
    def _infohash(release: dict[str, Any]) -> str:
        direct = str(release.get("infohash") or release.get("info_hash") or release.get("hash") or "").strip().lower()
        if direct:
            return direct
        match = _BTIH.search(str(release.get("magnet") or release.get("download") or ""))
        return match.group(1).lower() if match else ""

    @staticmethod
    def _integer(value: Any) -> int:
        text = str(value or "0").replace(",", "").strip()
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([kmgtpe]?i?b)?", text, re.I)
        if match:
            power = {"": 0, "b": 0, "kb": 1, "kib": 1, "mb": 2, "mib": 2, "gb": 3, "gib": 3, "tb": 4, "tib": 4, "pb": 5, "pib": 5, "eb": 6, "eib": 6}.get((match.group(2) or "").casefold(), 0)
            return int(float(match.group(1)) * (1024 ** power))
        try:
            return int(float(text))
        except ValueError:
            return 0

    def _normalize(self, release: dict[str, Any], definition: Any) -> dict[str, Any] | None:
        title = str(release.get("title") or release.get("name") or "").strip()
        if not title:
            return None
        infohash = self._infohash(release)
        magnet = str(release.get("magnet") or "").strip()
        if not magnet and infohash:
            magnet = CardigannEngine.magnet_for_hash(infohash, title)
        canonical = str(release.get("details") or release.get("link") or release.get("download") or "").strip()
        release_base = str(release.get("_base_url") or "")
        links = [release_base] if release_base else list(getattr(definition, "links", None) or [])
        if canonical and links:
            canonical = urljoin(str(links[0]).rstrip("/") + "/", canonical)
        result_id = torrent_result_id(infohash, canonical or magnet)
        category = str(release.get("category") or release.get("categories") or "")
        size = self._integer(release.get("size"))
        return {
            "result_id": result_id, "provider_group": "torrents", "source": "torrent", "source_label": "Torrent",
            "kind": "torrent", "kind_label": "Torrent", "title": title, "subtitle": category, "artist": "", "album": "",
            "year": "", "duration": 0, "thumbnail": "", "canonical_url": canonical, "stable_source_id": infohash,
            "search_blob": "", "filter_values": {"sources": ["Torrent"], "types": ["Torrent"], "indexers": [definition.name], "media": []},
            "match_confidence": 0.0, "rank_score": 0.0, "browse_available": True, "stream_available": False,
            "download_available": True, "files_loaded": False, "file_count": 0, "size": size, "files": [],
            "provider_data": {"infohash": infohash, "magnet": magnet, "indexer_ids": [definition.id], "indexer_labels": [definition.name], "source_urls": [canonical] if canonical else [], "seeders": self._integer(release.get("seeders")), "leechers": self._integer(release.get("leechers") or release.get("peers")), "verified": bool(release.get("verified")), "category": category},
        }

    def _search_one(self, definition: Any, query: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        started = time.monotonic()
        engine = self.engine_factory(definition)
        client = self.client_factory(definition.id)
        releases: list[dict[str, Any]] = []
        errors: list[str] = []
        requests = engine.generate_search_requests(query)
        attempted_bases: list[str] = []
        skipped_base: str | None = None
        for spec in requests:
            base_url = str(getattr(spec, "base_url", "") or "")
            if skipped_base and base_url == skipped_base:
                continue
            if base_url and base_url not in attempted_bases:
                if len(attempted_bases) >= _MAX_SEARCH_MIRRORS:
                    break
                attempted_bases.append(base_url)
            try:
                if hasattr(client, "rate_limit"):
                    client.rate_limit = max(float(getattr(client, "rate_limit", 0) or 0), float(getattr(spec, "delay_seconds", 0) or 0))
                response = client.request(spec.method, spec.url, headers=spec.headers, data=spec.data, allow_redirects=getattr(spec, "follow_redirects", True))
                if bool(getattr(response, "_debripod_challenge_failed", False)):
                    errors.append("challenge: " + str(getattr(response, "_debripod_challenge_error", "challenge solver failed")))
                    break
                if getattr(spec, "preflight", False):
                    continue
                parsed = engine.parse(response, spec, query=query) if isinstance(engine, CardigannEngine) else engine.parse(response)
                if parsed.error_classification in {"", "no_results"}:
                    for release in parsed.releases:
                        release.setdefault("_base_url", getattr(spec, "base_url", ""))
                    releases.extend(parsed.releases)
                    if parsed.releases or parsed.no_results:
                        break
                else:
                    errors.append(parsed.error_classification + ": " + parsed.diagnostic_summary)
                    if parsed.error_classification == "http_error":
                        skipped_base = base_url
            except Exception as exc:
                errors.append(str(exc))
                skipped_base = base_url
        rows = [row for release in releases if (row := self._normalize(release, definition))]
        rows = [row for row in rows if not assess_match(query, row).unrelated]
        status = {"indexer_id": definition.id, "label": definition.name, "status": "ok" if not errors or rows else "error", "error": "; ".join(errors), "result_count": len(rows), "duration_ms": int((time.monotonic() - started) * 1000)}
        return rows, status

    def search(self, query: str, context: Any = None) -> ProviderSearchResponse:
        started = time.monotonic()
        enabled = self._enabled()
        definitions = self.definition_store.list_active_definitions()
        candidates = []
        statuses: list[dict[str, Any]] = []
        for definition in definitions:
            if definition.id not in enabled:
                continue
            if definition.requires_setup or not definition.eligible:
                statuses.append({"indexer_id": definition.id, "label": definition.name, "status": "requires_setup" if definition.requires_setup else "invalid", "error": definition.parse_error, "result_count": 0})
            elif self.status_store.is_blocked(definition.id):
                status = self.status_store.get(definition.id)
                statuses.append({"indexer_id": definition.id, "label": definition.name, "status": "blocked", "blocked_until": status.disabled_until, "error": status.last_error_category, "result_count": 0})
            else:
                candidates.append(definition)
        rows: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.max_concurrent, thread_name_prefix="cardigann") as executor:
            futures = {executor.submit(self._search_one, definition, query): definition for definition in candidates}
            for future in as_completed(futures):
                definition = futures[future]
                try:
                    found, status = future.result()
                    rows.extend(found)
                    statuses.append(status)
                except Exception as exc:
                    statuses.append({"indexer_id": definition.id, "label": definition.name, "status": "error", "error": str(exc), "result_count": 0})
        merged = deduplicate_torrents(rows)
        error = "" if merged or not any(item.get("status") == "error" for item in statuses) else "All enabled torrent indexers failed"
        return ProviderSearchResponse("torrents", statuses, merged, error=error, duration_ms=int((time.monotonic() - started) * 1000))

    def resolve_release(self, indexer_id: str, release: dict[str, Any]) -> dict[str, Any]:
        definition = self.definition_store.load_definition(str(indexer_id or ""))
        if definition is None or not definition.eligible or definition.requires_setup:
            raise ValueError("Indexer is unavailable or requires setup")
        candidate = str(release.get("magnet") or release.get("download") or release.get("canonical_url") or "").strip()
        if not candidate:
            raise ValueError("Torrent result has no resolvable source URL")
        if not candidate.startswith("magnet:"):
            host = (urlparse(candidate).hostname or "").casefold()
            allowed = {(urlparse(link).hostname or "").casefold() for link in [*definition.links, *(definition.extra.get("legacylinks") or [])]}
            if not host or host not in allowed:
                raise ValueError("Torrent source URL does not belong to the selected indexer")
        engine = self.engine_factory(definition)
        client = self.client_factory(definition.id)

        def fetch(spec: RequestSpec):
            if hasattr(client, "rate_limit"):
                client.rate_limit = max(float(getattr(client, "rate_limit", 0) or 0), float(spec.delay_seconds or 0))
            return client.request(spec.method, spec.url, headers=spec.headers, data=spec.data, allow_redirects=False)

        return engine.resolve_download({
            "title": str(release.get("title") or ""),
            "infohash": str(release.get("infohash") or ""),
            "magnet": str(release.get("magnet") or ""),
            "download": candidate,
        }, fetch)


TorrentSearchProvider = IndexerService

from __future__ import annotations

import hashlib
import mimetypes
import os
import threading
import time
from typing import Any, Iterable, List

import requests

from ...media_types import AUDIO_EXTS, VIDEO_EXTS
from .base import DebridAuthError, DebridProviderBase, DebridProviderError
from .models import DebridFile, DebridPreview, DebridResolvedLink


_CACHE_LOCK = threading.Lock()
_PREVIEW_CACHE: dict[str, tuple[float, DebridPreview, str]] = {}


def _source_id(source: str) -> str:
    return hashlib.sha1(str(source or "").encode("utf-8", "ignore")).hexdigest()[:16]


class PremiumizeProvider(DebridProviderBase):
    id = "premiumize"
    label = "Premiumize"

    def __init__(self, token: str, base_url: str, timeout_seconds: int = 25, cache_ttl_seconds: int = 3600):
        self.token = str(token or "").strip()
        self.base_url = str(base_url or "").rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds or 25))
        self.cache_ttl_seconds = max(1, min(int(cache_ttl_seconds or 3600), 3600))

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        if not self.token:
            raise DebridAuthError("Premiumize token is missing.")
        try:
            response = requests.request(
                method,
                self.base_url + path,
                headers={"Authorization": f"Bearer {self.token}", "User-Agent": "DebriPod/1.0"},
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise DebridProviderError(f"Debrid request failed: {exc}") from exc
        if response.status_code in {401, 403}:
            raise DebridAuthError("Premiumize rejected the configured token.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DebridProviderError("Debrid provider returned an invalid response.") from exc
        if response.status_code >= 400 or not isinstance(payload, dict) or str(payload.get("status") or "").lower() in {"error", "fail", "failed"}:
            raise DebridProviderError(f"Debrid request failed: {str(payload.get('message') or response.text or response.status_code)[:300]}")
        return payload

    def validate_token(self) -> dict:
        return self._request("GET", "/api/account/info")

    @staticmethod
    def _preview_from_payload(source: str, payload: dict) -> DebridPreview:
        task_id = _source_id(source)
        files: list[DebridFile] = []
        for item in payload.get("content") or []:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or item.get("name") or "")
            link = str(item.get("link") or "")
            file_id = hashlib.sha1((path + "|" + link).encode("utf-8", "ignore")).hexdigest()[:16]
            ext = os.path.splitext(path)[1].lower()
            files.append(DebridFile(
                file_id=file_id,
                path=path,
                name=os.path.basename(path) or path,
                bytes=int(item.get("size") or 0),
                provider_link=link,
                provider_task_id=task_id,
                provider_file_id=file_id,
                media="video" if ext in VIDEO_EXTS else ("audio" if ext in AUDIO_EXTS else ""),
                ext=ext.lstrip("."),
                raw=dict(item),
            ))
        queued_id = str(payload.get("id") or payload.get("transfer_id") or "")
        return DebridPreview(
            provider="premiumize",
            provider_task_id=task_id,
            title=str(payload.get("name") or ""),
            status="ready" if files else ("queued" if queued_id else str(payload.get("status") or "")),
            files=files,
            raw={**payload, "queued_transfer_id": queued_id, "source": source},
            ready=bool(files),
        )

    def _cache(self, source: str, preview: DebridPreview) -> DebridPreview:
        with _CACHE_LOCK:
            _PREVIEW_CACHE[preview.provider_task_id] = (time.time(), preview, source)
        return preview

    def _cached(self, task_id: str) -> tuple[DebridPreview | None, str]:
        with _CACHE_LOCK:
            item = _PREVIEW_CACHE.get(task_id)
            if not item:
                return None, ""
            created, preview, source = item
            if time.time() - created > self.cache_ttl_seconds:
                _PREVIEW_CACHE.pop(task_id, None)
                return None, source
            return preview, source

    def preview_magnet(self, magnet: str) -> DebridPreview:
        payload = self._request("POST", "/api/transfer/directdl", data={"src": magnet})
        preview = self._preview_from_payload(magnet, payload)
        if not preview.files and preview.raw.get("queued_transfer_id"):
            # directdl may explicitly queue a transfer. Keep the cloud-transfer
            # fallback isolated to this response shape.
            try:
                created = self._create_transfer(magnet)
                preview.raw["queued_transfer_id"] = str(created.get("id") or preview.raw.get("queued_transfer_id") or "")
            except DebridProviderError:
                pass
        return self._cache(magnet, preview)

    def refresh_preview(self, provider_task_id: str) -> DebridPreview:
        preview, _source = self._cached(provider_task_id)
        if preview is None:
            raise DebridProviderError("Premiumize preview expired; preview the magnet again.")
        return preview

    def prepare_selected_files(
        self, *, magnet: str, provider_task_id: str, selected_file_ids: Iterable[str],
        timeout_seconds: int, poll_interval_seconds: int,
    ) -> List[DebridFile]:
        wanted = {str(value) for value in selected_file_ids if str(value or "").strip()}
        if not wanted:
            raise DebridProviderError("No files selected.")
        preview, source = self._cached(provider_task_id)
        source = magnet or source
        deadline = time.time() + max(1, int(timeout_seconds or 0))
        while preview is None or not preview.ready:
            if not source:
                raise DebridProviderError("Premiumize preview expired; preview the magnet again.")
            payload = self._request("POST", "/api/transfer/directdl", data={"src": source})
            preview = self._cache(source, self._preview_from_payload(source, payload))
            if preview.ready:
                break
            if time.time() >= deadline:
                raise DebridProviderError("Timed out waiting for debrid provider.")
            time.sleep(max(1, int(poll_interval_seconds or 1)))
        return [item for item in preview.files if item.file_id in wanted]

    def resolve_file_url(self, file: DebridFile) -> DebridResolvedLink:
        if not file.provider_link:
            raise DebridProviderError("No downloadable links available from debrid provider.")
        return DebridResolvedLink(
            url=file.provider_link,
            filename=file.name,
            size=file.bytes,
            mime=mimetypes.guess_type(file.name)[0] or "",
            requires_refresh=True,
            raw=file.raw,
        )

    def _create_transfer(self, source: str) -> dict:
        return self._request("POST", "/api/transfer/create", data={"src": source})

    def _transfer_list(self) -> dict:
        return self._request("GET", "/api/transfer/list")

    def _delete_transfer(self, transfer_id: str) -> dict:
        return self._request("POST", "/api/transfer/delete", data={"id": transfer_id})

    def delete_task_best_effort(self, provider_task_id: str | None) -> None:
        if not provider_task_id:
            return
        preview, _source = self._cached(provider_task_id)
        transfer_id = str((preview.raw if preview else {}).get("queued_transfer_id") or "")
        if transfer_id:
            try:
                self._delete_transfer(transfer_id)
            except Exception:
                pass

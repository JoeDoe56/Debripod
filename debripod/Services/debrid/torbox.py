from __future__ import annotations

import mimetypes
import os
import asyncio
import json
from typing import Any, Iterable, List

import aiohttp

from ...media_types import AUDIO_EXTS, VIDEO_EXTS
from ..http import HttpClient, HttpStatusError
from .base import DebridAuthError, DebridProviderBase, DebridProviderError
from .models import DebridFile, DebridPreview, DebridResolvedLink
from .identifiers import first_identifier, identifiers_equal, normalize_identifier, normalize_identifier_list


def find_torbox_files(payload: Any) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    candidates: list[dict] = []
    for key in ("files", "file_list", "contents"):
        if isinstance(payload.get(key), list):
            candidates.extend(item for item in payload[key] if isinstance(item, dict))
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("files", "file_list", "contents"):
            if isinstance(data.get(key), list):
                candidates.extend(item for item in data[key] if isinstance(item, dict))
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                for key in ("files", "file_list", "contents"):
                    if isinstance(item.get(key), list):
                        candidates.extend(value for value in item[key] if isinstance(value, dict))
    return candidates


def _task_payload(payload: dict, task_id: str) -> dict:
    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and identifiers_equal(first_identifier(item, "id", "torrent_id"), task_id):
                return item
        return next((item for item in data if isinstance(item, dict)), {})
    if isinstance(data, dict):
        return data
    return payload


class TorBoxProvider(DebridProviderBase):
    id = "torbox"
    label = "TorBox"

    def __init__(self, token: str, base_url: str, timeout_seconds: int, http: HttpClient):
        self.token = str(token or "").strip()
        self.base_url = str(base_url or "").rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds or 25))
        self.http = http

    async def _request(self, method: str, path: str, *, allow_text: bool = False, **kwargs: Any) -> Any:
        if not self.token:
            raise DebridAuthError("TorBox token is missing.")
        try:
            body, _headers, status = await self.http.bytes(
                method,
                self.base_url + path,
                headers={"Authorization": f"Bearer {self.token}", "User-Agent": "DebriPod/1.0"},
                timeout=self.timeout_seconds,
                **kwargs,
            )
            text = body.decode("utf-8", "replace")
        except HttpStatusError as exc:
            status = exc.status
            text = exc.body
        except Exception as exc:
            raise DebridProviderError(f"Debrid request failed: {exc}") from exc
        if status in {401, 403}:
            raise DebridAuthError("TorBox rejected the configured token.")
        if status >= 400:
            raise DebridProviderError(f"Debrid request failed ({status}): {text[:300]}")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            if allow_text:
                return text.strip()
            raise DebridProviderError("Debrid provider returned an invalid response.")
        if isinstance(payload, dict) and payload.get("success") is False:
            raise DebridProviderError(f"Debrid request failed: {str(payload.get('detail') or payload.get('error') or payload.get('message') or '')[:300]}")
        return payload

    async def validate_token(self) -> dict:
        # `/me` is the stable authenticated-account endpoint.  Stats can be
        # unavailable for an otherwise valid account/plan, so it must not be
        # used as the token validity probe.
        data = await self._request("GET", "/v1/api/user/me")
        return data if isinstance(data, dict) else {}

    async def preview_magnet(self, magnet: str) -> DebridPreview:
        form = aiohttp.FormData()
        form.add_field("magnet", magnet)
        data = await self._request("POST", "/v1/api/torrents/createtorrent", data=form)
        task = _task_payload(data if isinstance(data, dict) else {}, "")
        task_id = first_identifier(task, "torrent_id", "id") or first_identifier(data if isinstance(data, dict) else {}, "id")
        if task_id is None:
            raise DebridProviderError("Debrid provider did not return a task id.")
        return await self.refresh_preview(task_id)

    async def refresh_preview(self, provider_task_id: str) -> DebridPreview:
        payload = await self._request("GET", "/v1/api/torrents/mylist", params={
            "id": provider_task_id, "bypass_cache": "false", "offset": 0, "limit": 1000,
        })
        if not isinstance(payload, dict):
            raise DebridProviderError("Debrid provider returned an invalid torrent response.")
        task = _task_payload(payload, provider_task_id)
        raw_files = find_torbox_files(task) or find_torbox_files(payload)
        files: list[DebridFile] = []
        for item in raw_files:
            file_id = first_identifier(item, "id", "file_id")
            path = str(item.get("path") or item.get("name") or item.get("short_name") or "")
            if file_id is None or not path:
                continue
            ext = os.path.splitext(path)[1].lower()
            files.append(DebridFile(
                file_id=file_id,
                path=path,
                name=os.path.basename(path) or path,
                bytes=int(item.get("size") or item.get("bytes") or 0),
                provider_task_id=provider_task_id,
                provider_file_id=file_id,
                media="video" if ext in VIDEO_EXTS else ("audio" if ext in AUDIO_EXTS else ""),
                ext=ext.lstrip("."),
                raw=dict(item),
            ))
        status = str(task.get("download_state") or task.get("status") or task.get("state") or "")
        ready = bool(files) and status.lower() not in {"queued", "downloading", "metadl", "checking", "stalled"}
        return DebridPreview(
            provider=self.id,
            provider_task_id=provider_task_id,
            title=str(task.get("name") or task.get("title") or ""),
            status=status,
            files=files,
            raw=payload,
            ready=ready,
        )

    async def prepare_selected_files(
        self, *, magnet: str, provider_task_id: str, selected_file_ids: Iterable[str],
        timeout_seconds: int, poll_interval_seconds: int,
    ) -> List[DebridFile]:
        wanted = set(normalize_identifier_list(selected_file_ids))
        if not wanted:
            raise DebridProviderError("No files selected.")
        deadline = asyncio.get_running_loop().time() + max(1, int(timeout_seconds or 0))
        while asyncio.get_running_loop().time() <= deadline:
            preview = await self.refresh_preview(provider_task_id)
            if preview.ready:
                return [item for item in preview.files if item.file_id in wanted]
            if preview.status.lower() in {"error", "failed", "dead"}:
                raise DebridProviderError(f"Debrid provider reported status: {preview.status}")
            await asyncio.sleep(max(1, int(poll_interval_seconds or 1)))
        raise DebridProviderError("Timed out waiting for debrid provider.")

    async def resolve_file_url(self, file: DebridFile) -> DebridResolvedLink:
        data = await self._request("GET", "/v1/api/torrents/requestdl", allow_text=True, params={
            "token": self.token,
            "torrent_id": file.provider_task_id,
            "file_id": normalize_identifier(file.provider_file_id) or normalize_identifier(file.file_id),
            "zip_link": "false",
            "redirect": "false",
            "append_name": "true",
        })
        url = ""
        raw: dict[str, Any] = {}
        if isinstance(data, str):
            url = data if data.startswith("http") else ""
        elif isinstance(data, dict):
            raw = data
            inner = data.get("data")
            if isinstance(inner, str):
                url = inner
            elif isinstance(inner, dict):
                url = str(inner.get("link") or inner.get("url") or inner.get("download") or "")
            url = url or str(data.get("download") or data.get("link") or data.get("url") or "")
        if not url:
            raise DebridProviderError("No downloadable links available from debrid provider.")
        return DebridResolvedLink(
            url=url,
            filename=file.name,
            size=file.bytes,
            mime=mimetypes.guess_type(file.name)[0] or "",
            requires_refresh=True,
            raw=raw,
        )

    async def delete_task_best_effort(self, provider_task_id: str | None) -> None:
        provider_task_id = normalize_identifier(provider_task_id)
        if provider_task_id is None:
            return
        try:
            await self._request("POST", "/v1/api/torrents/controltorrent", json_body={"torrent_id": provider_task_id, "action": "delete"})
        except Exception:
            pass

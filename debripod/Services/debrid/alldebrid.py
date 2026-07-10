from __future__ import annotations

import hashlib
import mimetypes
import os
import threading
import time
from typing import Any, Iterable, Iterator, List

import requests

from ...media_types import AUDIO_EXTS, VIDEO_EXTS
from .base import DebridAuthError, DebridProviderBase, DebridProviderError
from .models import DebridFile, DebridPreview, DebridResolvedLink


_RATE_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0


def _stable_file_id(link: str, path: str) -> str:
    return hashlib.sha1((str(link) + "|" + str(path)).encode("utf-8", "ignore")).hexdigest()[:16]


def _pick_magnet(data: Any, task_id: str = "") -> dict:
    if isinstance(data, dict):
        magnets = data.get("magnets")
        if isinstance(magnets, list):
            for item in magnets:
                if isinstance(item, dict) and (not task_id or str(item.get("id") or item.get("magnet") or "") == task_id):
                    return item
            return magnets[0] if magnets and isinstance(magnets[0], dict) else {}
        if isinstance(magnets, dict):
            return magnets
        magnet = data.get("magnet")
        if isinstance(magnet, dict):
            return magnet
        return data
    if isinstance(data, list):
        return next((item for item in data if isinstance(item, dict)), {})
    return {}


def flatten_alldebrid_files(node: Any, magnet_id: str, prefix: str = "") -> Iterator[DebridFile]:
    items = node if isinstance(node, list) else ([node] if isinstance(node, dict) else [])
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("n") or item.get("name") or "")
        path = f"{prefix}/{name}".strip("/")
        children = item.get("e") or item.get("files")
        if children:
            yield from flatten_alldebrid_files(children, magnet_id, path)
            continue
        link = str(item.get("l") or item.get("link") or "")
        if not link:
            continue
        file_id = _stable_file_id(link, path)
        ext = os.path.splitext(path)[1].lower()
        yield DebridFile(
            file_id=file_id,
            path=path,
            name=name or os.path.basename(path),
            bytes=int(item.get("s") or item.get("size") or 0),
            provider_link=link,
            provider_task_id=magnet_id,
            provider_file_id=file_id,
            media="video" if ext in VIDEO_EXTS else ("audio" if ext in AUDIO_EXTS else ""),
            ext=ext.lstrip("."),
            raw=dict(item),
        )


class AllDebridProvider(DebridProviderBase):
    id = "alldebrid"
    label = "AllDebrid"

    def __init__(self, token: str, base_url: str, timeout_seconds: int = 25):
        self.token = str(token or "").strip()
        self.base_url = str(base_url or "").rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds or 25))

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        global _LAST_REQUEST_AT
        if not self.token:
            raise DebridAuthError("AllDebrid token is missing.")
        with _RATE_LOCK:
            delay = (1.0 / 12.0) - (time.monotonic() - _LAST_REQUEST_AT)
            if delay > 0:
                time.sleep(delay)
            _LAST_REQUEST_AT = time.monotonic()
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
            raise DebridAuthError("AllDebrid rejected the configured token.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DebridProviderError("Debrid provider returned an invalid response.") from exc
        if response.status_code >= 400 or not isinstance(payload, dict) or str(payload.get("status") or "").lower() == "error":
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                error = error.get("message") or error.get("code")
            raise DebridProviderError(f"Debrid request failed: {str(error or response.text or response.status_code)[:300]}")
        data = payload.get("data")
        return data if isinstance(data, dict) else {"value": data}

    def validate_token(self) -> dict:
        return self._request("GET", "/v4/user")

    def preview_magnet(self, magnet: str) -> DebridPreview:
        data = self._request("POST", "/v4/magnet/upload", data={"magnets[]": magnet})
        item = _pick_magnet(data)
        task_id = str(item.get("id") or item.get("magnet") or "")
        if not task_id:
            raise DebridProviderError("Debrid provider did not return a task id.")
        return self.refresh_preview(task_id)

    def refresh_preview(self, provider_task_id: str) -> DebridPreview:
        status_data = self._request("POST", "/v4.1/magnet/status", data={"id": provider_task_id})
        item = _pick_magnet(status_data, provider_task_id)
        status = str(item.get("status") or item.get("statusCode") or "")
        ready = status.lower() in {"ready", "downloaded", "complete", "completed"} or bool(item.get("links"))
        tree: Any = item.get("files") or item.get("links") or []
        if ready or not tree:
            try:
                files_data = self._request("POST", "/v4/magnet/files", data={"id[]": provider_task_id})
                files_item = _pick_magnet(files_data, provider_task_id)
                tree = files_item.get("files") or files_item.get("links") or files_data.get("files") or tree
            except DebridProviderError:
                if ready:
                    raise
        files = list(flatten_alldebrid_files(tree, provider_task_id))
        return DebridPreview(
            provider=self.id,
            provider_task_id=provider_task_id,
            title=str(item.get("filename") or item.get("name") or ""),
            status=status,
            files=files,
            raw={"status": status_data, "magnet": item},
            ready=bool(ready and files),
        )

    def prepare_selected_files(
        self, *, magnet: str, provider_task_id: str, selected_file_ids: Iterable[str],
        timeout_seconds: int, poll_interval_seconds: int,
    ) -> List[DebridFile]:
        wanted = {str(value) for value in selected_file_ids if str(value or "").strip()}
        if not wanted:
            raise DebridProviderError("No files selected.")
        deadline = time.time() + max(1, int(timeout_seconds or 0))
        while time.time() <= deadline:
            preview = self.refresh_preview(provider_task_id)
            if preview.ready:
                return [item for item in preview.files if item.file_id in wanted]
            if preview.status.lower() in {"error", "failed", "dead"}:
                raise DebridProviderError(f"Debrid provider reported status: {preview.status}")
            time.sleep(max(1, int(poll_interval_seconds or 1)))
        raise DebridProviderError("Timed out waiting for debrid provider.")

    def resolve_file_url(self, file: DebridFile) -> DebridResolvedLink:
        data = self._request("POST", "/v4/link/unlock", data={"link": file.provider_link})
        url = str(data.get("link") or "")
        delayed = data.get("delayed")
        if not url and delayed:
            deadline = time.time() + self.timeout_seconds
            while time.time() <= deadline:
                result = self._request("POST", "/v4/link/delayed", data={"id": delayed})
                url = str(result.get("link") or "")
                if url:
                    data = result
                    break
                time.sleep(1)
        if not url and isinstance(data.get("streams"), list):
            streams = [item for item in data["streams"] if isinstance(item, dict)]
            streams.sort(key=lambda item: (0 if str(item.get("ext") or "").lower() == "mp4" else 1, str(item.get("name") or "")))
            if streams:
                stream = streams[0]
                stream_id = stream.get("id") or stream.get("stream")
                unlock_id = data.get("id") or data.get("link")
                result = self._request("POST", "/v4/link/streaming", data={"id": unlock_id, "stream": stream_id})
                url = str(result.get("link") or result.get("url") or "")
                data = result
        if not url:
            raise DebridProviderError("No downloadable links available from debrid provider.")
        filename = str(data.get("filename") or data.get("name") or file.name)
        return DebridResolvedLink(
            url=url,
            filename=filename,
            size=int(data.get("size") or file.bytes or 0),
            mime=mimetypes.guess_type(filename)[0] or "",
            requires_refresh=True,
            raw=data,
        )

    def delete_task_best_effort(self, provider_task_id: str | None) -> None:
        if not provider_task_id:
            return
        try:
            self._request("POST", "/v4/magnet/delete", data={"id": provider_task_id})
        except Exception:
            pass

from __future__ import annotations

import mimetypes
import os
import time
from typing import Any, Iterable, List

import requests

from ...media_types import AUDIO_EXTS, VIDEO_EXTS
from .base import DebridAuthError, DebridProviderBase, DebridProviderError
from .models import DebridFile, DebridPreview, DebridResolvedLink


class RealDebridProvider(DebridProviderBase):
    id = "real_debrid"
    label = "Real Debrid"

    def __init__(self, token: str, base_url: str, timeout_seconds: int = 25):
        self.token = str(token or "").strip()
        self.base_url = str(base_url or "").rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds or 25))

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.token:
            raise DebridAuthError("Real Debrid token is missing.")
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
            raise DebridAuthError("Real Debrid rejected the configured token.")
        if response.status_code >= 400:
            raise DebridProviderError(f"Debrid request failed ({response.status_code}): {(response.text or '')[:300]}")
        if response.status_code == 204 or not (response.text or "").strip():
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise DebridProviderError("Debrid provider returned an invalid response.") from exc
        # Real Debrid can report invalid credentials as a JSON error payload
        # while still responding with HTTP 200.  Treat that as a failure so a
        # token from another provider is not falsely detected as Real Debrid.
        if isinstance(payload, dict) and payload.get("error"):
            detail = str(payload.get("error") or payload.get("message") or "Real Debrid request failed.")
            if str(payload.get("error_code") or "") in {"1", "2", "8", "9"} or any(word in detail.lower() for word in ("token", "auth", "credential", "permission")):
                raise DebridAuthError("Real Debrid rejected the configured token.")
            raise DebridProviderError(f"Real Debrid request failed: {detail[:300]}")
        return payload

    @staticmethod
    def _file(raw: dict, task_id: str) -> DebridFile:
        path = str(raw.get("path") or raw.get("file_path") or raw.get("filename") or "")
        file_id = str(raw.get("id") or "")
        ext = os.path.splitext(path)[1].lower()
        media = "video" if ext in VIDEO_EXTS else ("audio" if ext in AUDIO_EXTS else "")
        return DebridFile(
            file_id=file_id,
            path=path,
            name=os.path.basename(path) or path,
            bytes=int(raw.get("bytes") or raw.get("size") or raw.get("filesize") or 0),
            provider_task_id=task_id,
            provider_file_id=file_id,
            media=media,
            ext=ext.lstrip("."),
            raw=dict(raw),
        )

    def validate_token(self) -> dict:
        data = self._request("GET", "/user")
        return data if isinstance(data, dict) else {}

    def preview_magnet(self, magnet: str) -> DebridPreview:
        data = self._request("POST", "/torrents/addMagnet", data={"magnet": magnet})
        task_id = str((data or {}).get("id") or "")
        if not task_id:
            raise DebridProviderError("Debrid provider did not return a task id.")
        return self.refresh_preview(task_id)

    def refresh_preview(self, provider_task_id: str) -> DebridPreview:
        data = self._request("GET", f"/torrents/info/{provider_task_id}")
        if not isinstance(data, dict):
            raise DebridProviderError("Debrid provider returned an invalid torrent response.")
        files = [self._file(item, provider_task_id) for item in (data.get("files") or []) if isinstance(item, dict)]
        status = str(data.get("status") or "")
        return DebridPreview(
            provider=self.id,
            provider_task_id=provider_task_id,
            title=str(data.get("filename") or ""),
            status=status,
            files=files,
            raw=data,
            ready=status.lower() == "downloaded" and bool(data.get("links")),
        )

    def prepare_selected_files(
        self, *, magnet: str, provider_task_id: str, selected_file_ids: Iterable[str],
        timeout_seconds: int, poll_interval_seconds: int,
    ) -> List[DebridFile]:
        wanted = [str(value) for value in selected_file_ids if str(value or "").strip()]
        if not wanted:
            raise DebridProviderError("No files selected.")
        self._request("POST", f"/torrents/selectFiles/{provider_task_id}", data={"files": ",".join(wanted)})
        deadline = time.time() + max(1, int(timeout_seconds or 0))
        while time.time() <= deadline:
            preview = self.refresh_preview(provider_task_id)
            status = preview.status.lower()
            if status in {"error", "magnet_error", "virus", "dead"}:
                raise DebridProviderError(f"Debrid provider reported status: {status}")
            links = preview.raw.get("links") or []
            selected = [item for item in preview.files if item.file_id in wanted]
            if status == "downloaded" and isinstance(links, list) and links:
                for item, link in zip(selected, links):
                    item.provider_link = str(link or "")
                return [item for item in selected if item.provider_link]
            time.sleep(max(1, int(poll_interval_seconds or 1)))
        raise DebridProviderError("Timed out waiting for debrid provider.")

    def resolve_file_url(self, file: DebridFile) -> DebridResolvedLink:
        data = self._request("POST", "/unrestrict/link", data={"link": file.provider_link})
        url = str((data or {}).get("download") or "")
        if not url:
            raise DebridProviderError("No downloadable links available from debrid provider.")
        filename = str((data or {}).get("filename") or file.name)
        return DebridResolvedLink(
            url=url,
            filename=filename,
            size=int((data or {}).get("filesize") or file.bytes or 0),
            mime=mimetypes.guess_type(filename)[0] or "",
            raw=data if isinstance(data, dict) else {},
        )

    def delete_task_best_effort(self, provider_task_id: str | None) -> None:
        if not provider_task_id:
            return
        try:
            self._request("DELETE", f"/torrents/delete/{provider_task_id}")
        except Exception:
            pass

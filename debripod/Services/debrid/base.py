from __future__ import annotations

from typing import Iterable, List, Optional

from .models import DebridFile, DebridPreview, DebridResolvedLink


class DebridProviderError(RuntimeError):
    pass


class DebridAuthError(DebridProviderError):
    pass


class DebridProviderBase:
    id: str = ""
    label: str = ""

    def validate_token(self) -> dict:
        raise NotImplementedError

    def preview_magnet(self, magnet: str) -> DebridPreview:
        raise NotImplementedError

    def refresh_preview(self, provider_task_id: str) -> DebridPreview:
        raise NotImplementedError

    def prepare_selected_files(
        self,
        *,
        magnet: str,
        provider_task_id: str,
        selected_file_ids: Iterable[str],
        timeout_seconds: int,
        poll_interval_seconds: int,
    ) -> List[DebridFile]:
        raise NotImplementedError

    def resolve_file_url(self, file: DebridFile) -> DebridResolvedLink:
        raise NotImplementedError

    def delete_task_best_effort(self, provider_task_id: Optional[str]) -> None:
        return None

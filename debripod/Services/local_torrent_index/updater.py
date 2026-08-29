from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..http import HttpClient
from .dmm import DMMGitHubRepository, DMMUpdater
from .service import DEFAULT_DB_PATH, LocalTorrentIndex
from .torrents_csv import TorrentsCSVGitRepository, TorrentsCSVUpdater


DEFAULT_UPDATE_DIR = Path(DEFAULT_DB_PATH).parent / "torrent_index_update"


class LocalIndexUpdater:
    """Non-overlapping orchestrator for both exact-commit local-index feeds."""

    def __init__(
        self,
        index: LocalTorrentIndex | None = None,
        *,
        update_dir: str | Path = DEFAULT_UPDATE_DIR,
        http: HttpClient | None = None,
        dmm_repository: Any = None,
        csv_repository: Any = None,
    ):
        self.index = index or LocalTorrentIndex()
        self.update_dir = Path(update_dir)
        if dmm_repository is None and http is None:
            raise ValueError("LocalIndexUpdater requires the shared HTTP client")
        self.dmm = DMMUpdater(self.index, dmm_repository or DMMGitHubRepository(http), self.update_dir)
        self.csv = TorrentsCSVUpdater(
            self.index,
            csv_repository or TorrentsCSVGitRepository(self.update_dir / "torrents-csv.git"),
        )
        self._lock = asyncio.Lock()
        self.state: dict[str, Any] = {"building": False, "error": "", "dmm": {}, "torrents_csv": {}}

    async def update(self, *, force: bool = False) -> dict[str, Any]:
        if self._lock.locked():
            return {**self.state, "already_running": True}
        async with self._lock:
            self.state = {"building": True, "error": "", "dmm": {}, "torrents_csv": {}}
            errors: list[str] = []
            await asyncio.to_thread(self.index.initialize)
            try:
                self.state["dmm"] = await self.dmm.update(force=force)
            except Exception as exc:
                self.state["dmm"] = {"status": "error", "error": str(exc)}
                errors.append("DMM: " + str(exc))
            try:
                self.state["torrents_csv"] = await asyncio.to_thread(self.csv.update, force=force)
            except Exception as exc:
                self.state["torrents_csv"] = {"status": "error", "error": str(exc)}
                errors.append("Torrents CSV: " + str(exc))
            finally:
                self.state["error"] = "; ".join(errors)
                self.state["building"] = False
                self.state["diagnostics"] = await asyncio.to_thread(self.index.diagnostics)
        return dict(self.state)

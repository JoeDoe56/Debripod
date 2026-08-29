from __future__ import annotations

import csv
import datetime as dt
import re
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urljoin, urlparse

from .service import LocalTorrentIndex, decode_infohash


TORRENTS_CSV_REPOSITORIES = (
    "https://git.torrents-csv.com/heretic/torrents-csv-data.git",
    "https://codeberg.org/heretic/torrents-csv-data.git",
    "https://github.com/heretic/torrents-csv-data.git",
)
TORRENTS_CSV_SERVER_REPOSITORIES = (
    "https://git.torrents-csv.com/heretic/torrents-csv-server.git",
    "https://codeberg.org/heretic/torrents-csv-server.git",
    "https://github.com/heretic/torrents-csv-server.git",
)
DEFAULT_FIELDS = (
    "infohash", "name", "size_bytes", "created_unix", "seeders", "leechers", "completed", "scraped_unix"
)


def _first(row: dict[str, Any], *names: str) -> Any:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _timestamp(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        try:
            parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
            return int(parsed.timestamp())
        except ValueError:
            return None


def normalize_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    raw_hash = decode_infohash(_first(row, "infohash", "info_hash", "hash") or "")
    return {
        "infohash": raw_hash.hex(),
        "name": str(_first(row, "name", "title") or "").strip(),
        "size_bytes": _first(row, "size_bytes", "size"),
        "created_unix": _timestamp(_first(row, "created_unix", "created", "created_at")),
        "seeders": _first(row, "seeders", "seed_count"),
        "leechers": _first(row, "leechers", "leech_count", "peers"),
        "completed": _first(row, "completed", "completed_count"),
        "scraped_unix": _timestamp(_first(row, "scraped_unix", "scraped_date", "scraped_at")),
    }


def iter_csv_rows(stream: Iterable[str]) -> Iterator[dict[str, Any]]:
    reader = csv.DictReader(stream)
    for row in reader:
        try:
            normalized = normalize_csv_row(dict(row))
        except ValueError:
            continue
        if normalized["name"]:
            yield normalized


def parse_diff_lines(lines: Iterable[str], fieldnames: Iterable[str]) -> tuple[set[str], dict[str, dict[str, Any]]]:
    removed: dict[str, dict[str, Any]] = {}
    added: dict[str, dict[str, Any]] = {}
    fields = [str(value) for value in fieldnames]
    for raw_line in lines:
        if raw_line.startswith(("diff ", "index ", "@@", "---", "+++")) or not raw_line:
            continue
        prefix = raw_line[0]
        if prefix not in {"-", "+"}:
            continue
        try:
            values = next(csv.reader([raw_line[1:].rstrip("\r\n")]))
            row = normalize_csv_row(dict(zip(fields, values)))
        except (StopIteration, ValueError):
            continue
        (removed if prefix == "-" else added)[row["infohash"]] = row
    # A modified row appears once on both sides; clear then set it in one DB transaction.
    return set(removed), added


def data_url_from_gitmodules(payload: str, server_url: str) -> str:
    """Resolve the dataset URL currently referenced by the server repository."""
    sections = re.split(r"(?m)^\s*\[submodule\s+[^]]+\]\s*$", str(payload or ""))
    candidates: list[str] = []
    for section in sections:
        values: dict[str, str] = {}
        for line in section.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip().casefold()] = value.strip()
        url = values.get("url", "")
        path = values.get("path", "")
        if url and ("torrents-csv-data" in url.casefold() or "torrents-csv-data" in path.casefold()):
            candidates.append(url)
    for candidate in candidates:
        if candidate.startswith("git@") and ":" in candidate:
            host, path = candidate[4:].split(":", 1)
            candidate = f"https://{host}/{path}"
        parsed = urlparse(candidate)
        resolved = candidate if parsed.scheme in {"http", "https"} else urljoin(server_url.rstrip("/") + "/", candidate)
        if urlparse(resolved).scheme in {"http", "https"}:
            return resolved
    return ""


class TorrentsCSVGitRepository:
    def __init__(
        self,
        path: str | Path,
        urls: Iterable[str] = TORRENTS_CSV_REPOSITORIES,
        server_urls: Iterable[str] = TORRENTS_CSV_SERVER_REPOSITORIES,
    ):
        self.path = Path(path)
        self.urls = tuple(str(url) for url in urls)
        self.server_urls = tuple(str(url) for url in server_urls)
        self.server_reference_path = self.path.parent / "torrents-csv-server-reference.git"
        self.remote_url = ""

    @staticmethod
    def _run(args: list[str], *, timeout: float = 300.0, text: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=text,
            encoding="utf-8" if text else None,
            errors="replace" if text else None,
            timeout=timeout,
            check=False,
        )

    def _referenced_data_urls(self) -> list[str]:
        store = self.server_reference_path
        if not (store / "HEAD").is_file():
            store.parent.mkdir(parents=True, exist_ok=True)
            initialized = self._run(["git", "init", "--bare", str(store)])
            if initialized.returncode:
                return []
        for server_url in self.server_urls:
            self._run(["git", "-C", str(store), "remote", "remove", "origin"])
            added = self._run(["git", "-C", str(store), "remote", "add", "origin", server_url])
            if added.returncode:
                continue
            fetched = self._run(
                ["git", "-C", str(store), "fetch", "--no-tags", "--depth=1", "origin", "HEAD"],
                timeout=120,
            )
            if fetched.returncode:
                continue
            shown = self._run(["git", "-C", str(store), "show", "FETCH_HEAD:.gitmodules"], timeout=30)
            if shown.returncode:
                continue
            resolved = data_url_from_gitmodules(shown.stdout, server_url)
            if resolved:
                return [resolved]
        return []

    def resolve_head(self) -> tuple[str, str]:
        errors: list[str] = []
        urls = list(dict.fromkeys([*self._referenced_data_urls(), *self.urls]))
        for url in urls:
            result = self._run(["git", "ls-remote", url, "HEAD"], timeout=60)
            sha = (result.stdout.strip().split() or [""])[0]
            if result.returncode == 0 and len(sha) == 40:
                self.remote_url = url
                return sha, url
            errors.append(result.stderr.strip())
        raise RuntimeError("unable to resolve Torrents CSV HEAD: " + "; ".join(value for value in errors if value))

    def _ensure_store(self) -> None:
        if not (self.path / "HEAD").is_file():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            result = self._run(["git", "init", "--bare", str(self.path)])
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "git init failed")

    def fetch(self, sha: str, url: str = "") -> None:
        self._ensure_store()
        remote = str(url or self.remote_url or self.urls[0])
        result = self._run(
            ["git", "-C", str(self.path), "fetch", "--no-tags", "--depth=1", remote, sha],
            timeout=1800,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"unable to fetch {sha}")

    def _stream_command(self, args: list[str]) -> Iterator[str]:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        try:
            yield from process.stdout
        finally:
            process.stdout.close()
            stderr = process.stderr.read() if process.stderr is not None else ""
            if process.stderr is not None:
                process.stderr.close()
            code = process.wait(timeout=1800)
            if code:
                raise RuntimeError(stderr.strip() or "git streaming command failed")

    def snapshot_rows(self, sha: str) -> Iterator[dict[str, Any]]:
        lines = self._stream_command(["git", "-C", str(self.path), "show", f"{sha}:torrents.csv"])
        yield from iter_csv_rows(lines)

    def header(self, sha: str) -> list[str]:
        process = subprocess.Popen(
            ["git", "-C", str(self.path), "show", f"{sha}:torrents.csv"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        line = process.stdout.readline()
        process.kill()
        process.wait(timeout=30)
        return next(csv.reader([line])) if line else list(DEFAULT_FIELDS)

    def diff(self, old_sha: str, new_sha: str) -> tuple[set[str], dict[str, dict[str, Any]]]:
        fields = self.header(new_sha)
        lines = self._stream_command(
            ["git", "-C", str(self.path), "diff", "--no-color", "--unified=0", old_sha, new_sha, "--", "torrents.csv"]
        )
        return parse_diff_lines(lines, fields)


class TorrentsCSVUpdater:
    def __init__(self, index: LocalTorrentIndex, repository: TorrentsCSVGitRepository | Any):
        self.index = index
        self.repository = repository

    def bootstrap(self, sha: str, url: str = "") -> dict[str, Any]:
        self.repository.fetch(sha, url)
        count = self.index.replace_csv_snapshot(self.repository.snapshot_rows(sha), sha)
        return {"changed": True, "mode": "snapshot", "sha": sha, "rows": count, "repository_url": url}

    def incremental(self, old_sha: str, new_sha: str, url: str = "") -> dict[str, Any]:
        self.repository.fetch(old_sha, url)
        self.repository.fetch(new_sha, url)
        removed, added = self.repository.diff(old_sha, new_sha)
        with self.index.transaction() as conn:
            for infohash in removed:
                self.index.remove_csv(conn, infohash)
            for row in added.values():
                self.index.set_csv(conn, row)
            self.index.set_meta(conn, "torrents_csv_commit_sha", new_sha)
            self.index.set_meta(conn, "torrents_csv_last_success_unix", int(dt.datetime.now().timestamp()))
            self.index.increment_generation(conn)
        return {
            "changed": bool(removed or added),
            "mode": "incremental",
            "sha": new_sha,
            "removed": len(removed),
            "added_or_changed": len(added),
            "repository_url": url,
        }

    def update(self, *, force: bool = False, cadence_seconds: int = 21600) -> dict[str, Any]:
        with closing(self.index.open()) as conn:
            old_sha = self.index.get_meta(conn, "torrents_csv_commit_sha")
            last_check = int(self.index.get_meta(conn, "torrents_csv_last_check_unix", "0") or 0)
        now = int(dt.datetime.now().timestamp())
        if not force and last_check and now - last_check < cadence_seconds:
            return {"changed": False, "mode": "cadence", "sha": old_sha}
        new_sha, url = self.repository.resolve_head()
        if old_sha == new_sha:
            with self.index.transaction() as conn:
                self.index.set_meta(conn, "torrents_csv_last_check_unix", now)
                self.index.set_meta(conn, "torrents_csv_repository_url", url)
            return {"changed": False, "mode": "unchanged", "sha": new_sha, "repository_url": url}
        if not old_sha:
            result = self.bootstrap(new_sha, url)
            with self.index.transaction() as conn:
                self.index.set_meta(conn, "torrents_csv_last_check_unix", now)
                self.index.set_meta(conn, "torrents_csv_repository_url", url)
            return result
        try:
            result = self.incremental(old_sha, new_sha, url)
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError, csv.Error):
            # Snapshot replacement clears only CSV membership; DMM-owned rows survive.
            result = self.bootstrap(new_sha, url)
        with self.index.transaction() as conn:
            self.index.set_meta(conn, "torrents_csv_last_check_unix", now)
            self.index.set_meta(conn, "torrents_csv_repository_url", url)
        return result

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import time
import zipfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from ..http import HttpClient
from .service import LocalTorrentIndex, decode_infohash


DMM_REPOSITORY = "debridmediamanager/hashlists"
DMM_HEAD_API = f"https://api.github.com/repos/{DMM_REPOSITORY}/commits/main"
_URI_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-$"
_HASHLIST_FRAGMENT = re.compile(r"hashlist#([^\"'<>\s]+)", re.I)


def _decompress(length: int, reset_value: int, get_value) -> str:
    dictionary: dict[int, str] = {}
    enlarge_in = 4
    dict_size = 4
    num_bits = 3
    data_value = get_value(0)
    data_position = reset_value
    data_index = 1

    def read_bits(width: int) -> int:
        nonlocal data_value, data_position, data_index
        bits = 0
        power = 1
        while power != (1 << width):
            result_bit = data_value & data_position
            data_position >>= 1
            if data_position == 0:
                data_position = reset_value
                data_value = get_value(data_index) if data_index < length else 0
                data_index += 1
            if result_bit:
                bits |= power
            power <<= 1
        return bits

    marker = read_bits(2)
    if marker == 0:
        first = chr(read_bits(8))
    elif marker == 1:
        first = chr(read_bits(16))
    else:
        return ""
    dictionary[3] = first
    word = first
    output = [first]
    while data_index <= length:
        code = read_bits(num_bits)
        if code == 0:
            dictionary[dict_size] = chr(read_bits(8))
            code = dict_size
            dict_size += 1
            enlarge_in -= 1
        elif code == 1:
            dictionary[dict_size] = chr(read_bits(16))
            code = dict_size
            dict_size += 1
            enlarge_in -= 1
        elif code == 2:
            return "".join(output)
        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1
        if code in dictionary:
            entry = dictionary[code]
        elif code == dict_size:
            entry = word + word[0]
        else:
            raise ValueError("invalid LZ-String payload")
        output.append(entry)
        dictionary[dict_size] = word + entry[0]
        dict_size += 1
        enlarge_in -= 1
        word = entry
        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1
    raise ValueError("unterminated LZ-String payload")


def decompress_uri_component(value: str) -> str:
    encoded = str(value or "").replace(" ", "+")
    if not encoded:
        return ""
    indexes = [_URI_ALPHABET.find(char) for char in encoded]
    if any(index < 0 for index in indexes):
        raise ValueError("invalid LZ-String URI alphabet")
    return _decompress(len(indexes), 32, indexes.__getitem__)


def decode_hashlist_html(payload: str | bytes) -> list[dict[str, Any]]:
    text = payload.decode("utf-8", "ignore") if isinstance(payload, bytes) else str(payload or "")
    match = _HASHLIST_FRAGMENT.search(text)
    if not match:
        return []
    decoded = json.loads(decompress_uri_component(match.group(1)))
    if isinstance(decoded, dict):
        values = decoded.get("torrents") or decoded.get("items") or decoded.get("hashlist") or [decoded]
    else:
        values = decoded
    if not isinstance(values, list):
        return []
    output: list[dict[str, Any]] = []
    seen: set[bytes] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        try:
            raw_hash = decode_infohash(item.get("hash") or item.get("infohash") or "")
        except ValueError:
            continue
        if raw_hash in seen:
            continue
        seen.add(raw_hash)
        output.append(
            {
                "hash": raw_hash.hex(),
                "filename": str(item.get("filename") or item.get("name") or ""),
                "bytes": item.get("bytes") if item.get("bytes") is not None else item.get("size"),
            }
        )
    return output


def iter_archive_hashlists(path: str | Path) -> Iterator[list[dict[str, Any]]]:
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            if member.is_dir() or not member.filename.lower().endswith(".html"):
                continue
            with archive.open(member) as handle:
                entries = decode_hashlist_html(handle.read())
                if not entries:
                    raise ValueError(f"invalid or empty DMM hashlist: {member.filename}")
                yield entries


@dataclass(slots=True)
class DMMCommit:
    sha: str
    parent_sha: str
    files: list[dict[str, str]]


class DMMGitHubRepository:
    def __init__(self, http: HttpClient, token: str = "", timeout: float = 60.0):
        self.http = http
        self.token = str(token or "")
        self.timeout = float(timeout)

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {"Accept": accept, "User-Agent": "DebriPod-local-index"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        return headers

    async def _json(self, url: str) -> Any:
        return await self.http.json("GET", url, headers=self._headers(), timeout=self.timeout)

    async def resolve_head(self) -> str:
        data = await self._json(DMM_HEAD_API)
        sha = str(data.get("sha") or "") if isinstance(data, dict) else ""
        if len(sha) != 40:
            raise RuntimeError("DMM HEAD did not return an exact commit SHA")
        return sha

    async def download_archive(self, sha: str, destination: str | Path) -> None:
        url = f"https://codeload.github.com/{DMM_REPOSITORY}/zip/{sha}"
        await self.http.download(
            "GET",
            url,
            destination,
            headers=self._headers("application/zip"),
            timeout=max(self.timeout, 1800.0),
        )

    async def commits_between(self, old_sha: str, new_sha: str, max_commits: int = 100) -> list[str]:
        data = await self._json(f"https://api.github.com/repos/{DMM_REPOSITORY}/compare/{old_sha}...{new_sha}")
        if not isinstance(data, dict) or data.get("status") not in {"ahead", "identical"}:
            raise RuntimeError("DMM history is not a supported linear forward update")
        total = int(data.get("total_commits") or 0)
        commits = [str(item.get("sha") or "") for item in data.get("commits") or []]
        if total > max_commits or len(commits) != total or any(len(sha) != 40 for sha in commits):
            raise RuntimeError("DMM commit range is too large or incomplete")
        return commits

    async def commit(self, sha: str) -> DMMCommit:
        data = await self._json(f"https://api.github.com/repos/{DMM_REPOSITORY}/commits/{sha}")
        files = (data.get("files") or []) if isinstance(data, dict) else []
        if len(files) >= 300:
            raise RuntimeError("DMM commit file listing may be truncated")
        parent = str(((data.get("parents") or [{}])[0]).get("sha") or "")
        normalized = [
            {
                "filename": str(item.get("filename") or ""),
                "previous_filename": str(item.get("previous_filename") or ""),
                "status": str(item.get("status") or ""),
            }
            for item in files
            if str(item.get("filename") or item.get("previous_filename") or "").lower().endswith(".html")
        ]
        return DMMCommit(sha=sha, parent_sha=parent, files=normalized)

    async def file(self, path: str, sha: str) -> bytes:
        url = f"https://raw.githubusercontent.com/{DMM_REPOSITORY}/{sha}/{path}"
        body, _headers, _status = await self.http.bytes(
            "GET",
            url,
            headers=self._headers("text/html"),
            timeout=self.timeout,
        )
        return body


class DMMUpdater:
    def __init__(self, index: LocalTorrentIndex, repository: DMMGitHubRepository | Any, update_dir: str | Path):
        self.index = index
        self.repository = repository
        self.update_dir = Path(update_dir)

    async def bootstrap(self, sha: str | None = None) -> dict[str, Any]:
        exact_sha = str(sha or await self.repository.resolve_head())
        self.update_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="dmm-", suffix=".zip", dir=self.update_dir, delete=False) as temp:
            archive_path = Path(temp.name)
        try:
            await self.repository.download_archive(exact_sha, archive_path)
            count = await asyncio.to_thread(
                lambda: self.index.replace_dmm_snapshot(iter_archive_hashlists(archive_path), exact_sha)
            )
            return {"changed": True, "mode": "snapshot", "sha": exact_sha, "memberships": count}
        finally:
            archive_path.unlink(missing_ok=True)

    @staticmethod
    def _entries(payload: bytes | None) -> dict[bytes, dict[str, Any]]:
        if payload is None:
            return {}
        entries = decode_hashlist_html(payload)
        if not entries:
            raise ValueError("invalid or empty DMM hashlist payload")
        return {decode_infohash(item["hash"]): item for item in entries}

    def _apply_incremental(self, batches: list[tuple[dict[bytes, dict[str, Any]], dict[bytes, dict[str, Any]]]], new_sha: str) -> None:
        with self.index.transaction() as conn:
            for old_entries, new_entries in batches:
                for raw_hash in old_entries.keys() - new_entries.keys():
                    self.index.remove_dmm(conn, raw_hash)
                for raw_hash in new_entries.keys() - old_entries.keys():
                    item = new_entries[raw_hash]
                    self.index.add_dmm(conn, raw_hash, item["filename"], item.get("bytes"))
            self.index.set_meta(conn, "dmm_commit_sha", new_sha)
            self.index.set_meta(conn, "dmm_last_success_unix", int(time.time()))
            self.index.increment_generation(conn)

    async def incremental(self, old_sha: str, new_sha: str) -> dict[str, Any]:
        commits = await self.repository.commits_between(old_sha, new_sha)
        batches: list[tuple[dict[bytes, dict[str, Any]], dict[bytes, dict[str, Any]]]] = []
        for sha in commits:
            commit = await self.repository.commit(sha)
            if len(commit.parent_sha) != 40:
                raise RuntimeError("DMM commit parent is unavailable")
            for change in commit.files:
                status = change["status"]
                new_path = change["filename"]
                old_path = change.get("previous_filename") or new_path
                old_future = asyncio.sleep(0, result=None) if status == "added" else self.repository.file(old_path, commit.parent_sha)
                new_future = asyncio.sleep(0, result=None) if status == "removed" else self.repository.file(new_path, sha)
                old_payload, new_payload = await asyncio.gather(old_future, new_future)
                batches.append((self._entries(old_payload), self._entries(new_payload)))
        await asyncio.to_thread(self._apply_incremental, batches, new_sha)
        return {"changed": bool(commits), "mode": "incremental", "sha": new_sha, "commits": len(commits)}

    async def update(self, *, force: bool = False, cadence_seconds: int = 21600) -> dict[str, Any]:
        with closing(self.index.open()) as conn:
            old_sha = self.index.get_meta(conn, "dmm_commit_sha")
            last_check = int(self.index.get_meta(conn, "dmm_last_check_unix", "0") or 0)
        now = int(time.time())
        if not force and last_check and now - last_check < cadence_seconds:
            return {"changed": False, "mode": "cadence", "sha": old_sha}
        new_sha = await self.repository.resolve_head()
        if old_sha == new_sha:
            with self.index.transaction() as conn:
                self.index.set_meta(conn, "dmm_last_check_unix", now)
            return {"changed": False, "mode": "unchanged", "sha": new_sha}
        if not old_sha:
            result = await self.bootstrap(new_sha)
            with self.index.transaction() as conn:
                self.index.set_meta(conn, "dmm_last_check_unix", now)
            return result
        try:
            result = await self.incremental(old_sha, new_sha)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError, zipfile.BadZipFile):
            result = await self.bootstrap(new_sha)
        with self.index.transaction() as conn:
            self.index.set_meta(conn, "dmm_last_check_unix", now)
        return result

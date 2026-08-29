from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from debripod.Services.local_index_search import LocalIndexSearchProvider
from debripod.Services.local_torrent_index.dmm import DMMCommit, DMMUpdater, decode_hashlist_html, decompress_uri_component
from debripod.Services.local_torrent_index.metadata import parse_release_name
from debripod.Services.local_torrent_index.schema import LOCAL_SOURCE_DMM, LOCAL_SOURCE_TORRENTS_CSV
from debripod.Services.local_torrent_index.service import LocalTorrentIndex, decode_infohash
from debripod.Services.local_torrent_index.torrents_csv import (
    TorrentsCSVUpdater,
    data_url_from_gitmodules,
    iter_csv_rows,
    parse_diff_lines,
)


HASH_A = "00" * 19 + "01"
HASH_B = "00" * 19 + "02"
HASH_C = "00" * 19 + "03"


@pytest.fixture
def index(tmp_path: Path) -> LocalTorrentIndex:
    value = LocalTorrentIndex(tmp_path / "torrent_index.sqlite")
    value.initialize()
    return value


def test_infohash_is_validated_and_stored_as_twenty_byte_blob(index: LocalTorrentIndex):
    with index.transaction() as conn:
        index.add_dmm(conn, HASH_A, "Example.Release.2025.1080p.WEB-DL", 123)
    with index.open() as conn:
        row = conn.execute("SELECT infohash,typeof(infohash),length(infohash) FROM torrents").fetchone()
        assert bytes(row[0]) == bytes.fromhex(HASH_A)
        assert row[1:] == ("blob", 20)
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    with pytest.raises(ValueError):
        decode_infohash("abcd")


def test_release_parser_reuses_video_tokens_and_compact_codes():
    parsed = parse_release_name("The.Matrix.1999.2160p.BluRay.x265-GROUP.mkv")
    assert parsed == {"parsed_title": "The Matrix", "year": 1999, "resolution": 2160, "quality": 5}


def test_dmm_refcounts_and_csv_membership_merge_without_losing_other_owner(index: LocalTorrentIndex):
    csv_row = {"infohash": HASH_A, "name": "Example 2025 1080p WEB-DL", "size_bytes": 500, "seeders": 10}
    with index.transaction() as conn:
        index.add_dmm(conn, HASH_A, "Example 2025 1080p WEB-DL", 500)
        index.add_dmm(conn, HASH_A, "duplicate in another hashlist", 500)
        index.set_csv(conn, csv_row)
    with index.open() as conn:
        row = conn.execute("SELECT source_mask,dmm_refcount,csv_present FROM torrents").fetchone()
        assert tuple(row) == (LOCAL_SOURCE_DMM | LOCAL_SOURCE_TORRENTS_CSV, 2, 1)
    response = asyncio.run(LocalIndexSearchProvider(index).search("example"))
    assert response.results[0]["filter_values"]["sources"] == ["Local Index"]
    assert response.results[0]["provider_data"]["indexer_labels"] == ["DMM", "Torrents CSV"]
    with index.transaction() as conn:
        index.remove_dmm(conn, HASH_A)
        index.remove_dmm(conn, HASH_A)
    with index.open() as conn:
        row = conn.execute("SELECT source_mask,dmm_refcount FROM torrents").fetchone()
        assert tuple(row) == (LOCAL_SOURCE_TORRENTS_CSV, 0)
    with index.transaction() as conn:
        index.remove_csv(conn, HASH_A)
    with index.open() as conn:
        assert conn.execute("SELECT COUNT(*) FROM torrents").fetchone()[0] == 0


def test_snapshot_deduplicates_each_dmm_hashlist_and_advances_sha_transactionally(index: LocalTorrentIndex):
    count = index.replace_dmm_snapshot(
        [
            [{"hash": HASH_A, "filename": "Alpha"}, {"hash": HASH_A, "filename": "Alpha duplicate"}],
            [{"hash": HASH_A, "filename": "Alpha again"}, {"hash": HASH_B, "filename": "Beta"}],
        ],
        "a" * 40,
    )
    assert count == 3
    with index.open() as conn:
        assert conn.execute("SELECT dmm_refcount FROM torrents WHERE infohash=?", (bytes.fromhex(HASH_A),)).fetchone()[0] == 2
        assert index.get_meta(conn, "dmm_commit_sha") == "a" * 40
        assert index.get_meta(conn, "local_index_generation") == "1"

    def interrupted():
        yield [{"hash": HASH_C, "filename": "Gamma"}]
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError):
        index.replace_dmm_snapshot(interrupted(), "b" * 40)
    with index.open() as conn:
        assert index.get_meta(conn, "dmm_commit_sha") == "a" * 40
        assert conn.execute("SELECT COUNT(*) FROM torrents WHERE infohash=?", (bytes.fromhex(HASH_C),)).fetchone()[0] == 0


def test_fts_search_returns_every_match_and_provider_keeps_blob_internal(index: LocalTorrentIndex):
    with index.transaction() as conn:
        for number in range(125):
            index.add_dmm(conn, f"{number + 1:040x}", f"Broad Match Release {number:03d} 1080p WEB-DL", number)
    rows = index.search("broad match")
    assert len(rows) == 125
    response = asyncio.run(LocalIndexSearchProvider(index).search("broad match"))
    assert len(response.results) == 125
    first = response.results[0]
    assert first["source"] == "local_index"
    assert first["filter_values"]["sources"] == ["Local Index"]
    assert len(first["provider_data"]["infohash"]) == 40
    assert isinstance(first["provider_data"]["infohash"], str)
    assert first["provider_data"]["magnet"].startswith("magnet:?xt=urn:btih:")

    with index.transaction() as conn:
        conn.execute(
            "UPDATE torrents SET name=?, parsed_title=? WHERE infohash=?",
            ("opaque-file-name", "Distinct Parsed Title", bytes.fromhex(f"{1:040x}")),
        )
    assert index.search("distinct parsed")[0]["parsed_title"] == "Distinct Parsed Title"


def test_dmm_lz_decoder_and_html_payload_validation(monkeypatch):
    assert decompress_uri_component("BIUwNmD2AEDukCcwBMg") == "Hello world"
    monkeypatch.setattr(
        "debripod.Services.local_torrent_index.dmm.decompress_uri_component",
        lambda _value: '[{"filename":"Alpha","hash":"' + HASH_A + '","bytes":42},'
        '{"filename":"duplicate","hash":"' + HASH_A + '"},'
        '{"filename":"invalid","hash":"xyz"}]',
    )
    assert decode_hashlist_html('<a href="hashlist#fixture">x</a>') == [
        {"hash": HASH_A, "filename": "Alpha", "bytes": 42}
    ]


def test_dmm_incremental_add_modify_delete_applies_oldest_first_and_rolls_back(index: LocalTorrentIndex, monkeypatch):
    index.replace_dmm_snapshot([[{"hash": HASH_A, "filename": "Alpha"}]], "a" * 40)

    class Repo:
        async def commits_between(self, old, new):
            assert old == "a" * 40 and new == "c" * 40
            return ["b" * 40, "c" * 40]

        async def commit(self, sha):
            if sha == "b" * 40:
                return DMMCommit(sha, "a" * 40, [{"filename": "one.html", "previous_filename": "", "status": "modified"}])
            return DMMCommit(sha, "b" * 40, [{"filename": "two.html", "previous_filename": "", "status": "added"}])

        async def file(self, path, sha):
            return f"{path}:{sha}".encode()

    mapping = {
        "one.html:" + "a" * 40: [{"hash": HASH_A, "filename": "Alpha"}],
        "one.html:" + "b" * 40: [{"hash": HASH_B, "filename": "Beta"}],
        "two.html:" + "c" * 40: [{"hash": HASH_C, "filename": "Gamma"}],
    }
    monkeypatch.setattr(
        "debripod.Services.local_torrent_index.dmm.decode_hashlist_html",
        lambda payload: mapping[payload.decode()],
    )
    updater = DMMUpdater(index, Repo(), index.path.parent / "updates")
    asyncio.run(updater.incremental("a" * 40, "c" * 40))
    with index.open() as conn:
        hashes = {bytes(row[0]).hex() for row in conn.execute("SELECT infohash FROM torrents")}
        assert hashes == {HASH_B, HASH_C}
        assert index.get_meta(conn, "dmm_commit_sha") == "c" * 40

    class BrokenRepo(Repo):
        async def file(self, path, sha):
            if sha == "c" * 40:
                raise RuntimeError("interrupted")
            return await super().file(path, sha)

    with pytest.raises(RuntimeError):
        asyncio.run(DMMUpdater(index, BrokenRepo(), index.path.parent / "updates").incremental("a" * 40, "c" * 40))
    with index.open() as conn:
        assert index.get_meta(conn, "dmm_commit_sha") == "c" * 40


def test_invalid_dmm_commit_payload_does_not_advance_sha_or_generation(index: LocalTorrentIndex):
    index.replace_dmm_snapshot([[{"hash": HASH_A, "filename": "Alpha"}]], "a" * 40)

    class InvalidRepo:
        async def commits_between(self, old, new):
            return [new]

        async def commit(self, sha):
            return DMMCommit(sha, "a" * 40, [{"filename": "bad.html", "previous_filename": "", "status": "added"}])

        async def file(self, path, sha):
            return b"<html>not a hashlist</html>"

    with pytest.raises(ValueError):
        asyncio.run(DMMUpdater(index, InvalidRepo(), index.path.parent / "updates").incremental("a" * 40, "b" * 40))
    with index.open() as conn:
        assert index.get_meta(conn, "dmm_commit_sha") == "a" * 40
        assert index.get_meta(conn, "local_index_generation") == "1"
        assert {bytes(row[0]).hex() for row in conn.execute("SELECT infohash FROM torrents")} == {HASH_A}


def test_torrents_csv_stream_parser_and_hash_keyed_diff():
    rows = list(iter_csv_rows([
        "infohash,name,size_bytes,created_unix,seeders,leechers,completed,scraped_unix\n",
        f'{HASH_A},"Alpha, Release",100,10,5,2,7,20\n',
        "bad,Invalid,1,1,1,1,1,1\n",
    ]))
    assert rows == [{
        "infohash": HASH_A, "name": "Alpha, Release", "size_bytes": "100", "created_unix": 10,
        "seeders": "5", "leechers": "2", "completed": "7", "scraped_unix": 20,
    }]
    removed, added = parse_diff_lines(
        [
            "@@ -2 +2 @@\n",
            f"-{HASH_A},Alpha,100,10,5,2,7,20\n",
            f"+{HASH_A},Alpha,100,10,9,1,8,30\n",
            f"+{HASH_B},Beta,200,11,2,0,3,31\n",
        ],
        ["infohash", "name", "size_bytes", "created_unix", "seeders", "leechers", "completed", "scraped_unix"],
    )
    assert removed == {HASH_A}
    assert set(added) == {HASH_A, HASH_B}
    assert added[HASH_A]["seeders"] == "9"


def test_torrents_csv_dataset_url_is_resolved_from_server_submodule_reference():
    payload = """
[submodule "torrents-csv-data"]
    path = torrents-csv-data
    url = ../torrents-csv-data.git
"""
    assert data_url_from_gitmodules(
        payload,
        "https://codeberg.org/heretic/torrents-csv-server.git",
    ) == "https://codeberg.org/heretic/torrents-csv-data.git"


def test_csv_snapshot_reconciliation_preserves_dmm_and_sha_on_interruption(index: LocalTorrentIndex):
    with index.transaction() as conn:
        index.add_dmm(conn, HASH_A, "DMM Alpha")
        index.set_csv(conn, {"infohash": HASH_A, "name": "CSV Alpha"})
    index.replace_csv_snapshot([{"infohash": HASH_B, "name": "CSV Beta"}], "d" * 40)
    with index.open() as conn:
        rows = {bytes(row["infohash"]).hex(): row["source_mask"] for row in conn.execute("SELECT infohash,source_mask FROM torrents")}
        assert rows == {HASH_A: LOCAL_SOURCE_DMM, HASH_B: LOCAL_SOURCE_TORRENTS_CSV}

    def interrupted():
        yield {"infohash": HASH_C, "name": "CSV Gamma"}
        raise OSError("interrupted")

    with pytest.raises(OSError):
        index.replace_csv_snapshot(interrupted(), "e" * 40)
    with index.open() as conn:
        assert index.get_meta(conn, "torrents_csv_commit_sha") == "d" * 40
        assert {bytes(row[0]).hex() for row in conn.execute("SELECT infohash FROM torrents")} == {HASH_A, HASH_B}


def test_csv_incremental_add_update_delete_is_transactional_and_preserves_dmm(index: LocalTorrentIndex):
    with index.transaction() as conn:
        index.add_dmm(conn, HASH_A, "DMM Alpha")
        index.set_csv(conn, {"infohash": HASH_A, "name": "CSV Alpha", "seeders": 1})
        index.set_csv(conn, {"infohash": HASH_B, "name": "CSV Beta", "seeders": 2})
        index.set_meta(conn, "torrents_csv_commit_sha", "a" * 40)

    class Repo:
        def fetch(self, *_args):
            return None

        def diff(self, old, new):
            assert (old, new) == ("a" * 40, "b" * 40)
            return {HASH_A, HASH_B}, {
                HASH_A: {"infohash": HASH_A, "name": "CSV Alpha refreshed", "seeders": 10},
                HASH_C: {"infohash": HASH_C, "name": "CSV Gamma", "seeders": 3},
            }

    TorrentsCSVUpdater(index, Repo()).incremental("a" * 40, "b" * 40, "fixture")
    with index.open() as conn:
        rows = {bytes(row["infohash"]).hex(): row for row in conn.execute("SELECT * FROM torrents")}
        assert set(rows) == {HASH_A, HASH_C}
        assert rows[HASH_A]["source_mask"] == LOCAL_SOURCE_DMM | LOCAL_SOURCE_TORRENTS_CSV
        assert rows[HASH_A]["csv_seeders"] == 10
        assert rows[HASH_C]["source_mask"] == LOCAL_SOURCE_TORRENTS_CSV
        assert index.get_meta(conn, "torrents_csv_commit_sha") == "b" * 40

    class InterruptedRepo(Repo):
        def diff(self, old, new):
            raise OSError("interrupted diff")

    with pytest.raises(OSError):
        TorrentsCSVUpdater(index, InterruptedRepo()).incremental("b" * 40, "c" * 40, "fixture")
    with index.open() as conn:
        assert index.get_meta(conn, "torrents_csv_commit_sha") == "b" * 40
        assert {bytes(row[0]).hex() for row in conn.execute("SELECT infohash FROM torrents")} == {HASH_A, HASH_C}

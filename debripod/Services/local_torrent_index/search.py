from __future__ import annotations

import re
import sqlite3
from typing import Any


def fts_query(value: str) -> str:
    tokens = re.findall(r"[\w]+", str(value or ""), flags=re.UNICODE)
    return " AND ".join('"' + token.replace('"', '""') + '"*' for token in tokens)


def search_rows(conn: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    expression = fts_query(query)
    if not expression:
        return []
    rows = conn.execute(
        """
        SELECT t.*, bm25(torrent_search) AS fts_rank
        FROM torrent_search
        JOIN torrents AS t ON t.id = torrent_search.rowid
        WHERE torrent_search MATCH ?
        ORDER BY fts_rank ASC, COALESCE(t.csv_seeders, 0) DESC, t.id ASC
        """,
        (expression,),
    ).fetchall()
    return [dict(row) for row in rows]

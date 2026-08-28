from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

from ...storage.database import database


BACKOFF_PERIODS = [0, 60, 300, 900, 1800, 3600, 10800, 21600, 43200, 86400]


@dataclass(slots=True)
class IndexerStatus:
    indexer_id: str
    initial_failure_time: float | None = None
    most_recent_failure_time: float | None = None
    escalation_level: int = 0
    disabled_until: float | None = None
    last_success: float | None = None
    last_error_category: str = ""
    cookies_json: str = "[]"
    cookies_expiration: float | None = None
    last_challenge_solve: float | None = None
    last_response_duration: float = 0.0
    user_agent: str = ""

    @property
    def cookies(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.cookies_json or "[]")
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []


class IndexerStatusStore:
    def __init__(self, *, now: Callable[[], float] = time.time, database_context: Callable[..., Any] = database, startup_at: float | None = None):
        self.now = now
        self.database_context = database_context
        self.startup_at = float(startup_at if startup_at is not None else now())

    def get(self, indexer_id: str) -> IndexerStatus:
        with self.database_context(write=False) as conn:
            row = conn.execute("SELECT * FROM indexer_status WHERE indexer_id=?", (indexer_id,)).fetchone()
        return IndexerStatus(**dict(row)) if row else IndexerStatus(indexer_id)

    def save(self, status: IndexerStatus) -> IndexerStatus:
        fields = asdict(status)
        columns = list(fields)
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{name}=excluded.{name}" for name in columns if name != "indexer_id")
        with self.database_context() as conn:
            conn.execute(f"INSERT INTO indexer_status({','.join(columns)}) VALUES({placeholders}) ON CONFLICT(indexer_id) DO UPDATE SET {updates}", tuple(fields[name] for name in columns))
        return status

    def record_failure(self, indexer_id: str, category: str, *, retry_after: float | None = None, duration_ms: float = 0.0, connection_failure: bool = False) -> IndexerStatus:
        now = self.now()
        status = self.get(indexer_id)
        status.initial_failure_time = status.initial_failure_time or now
        status.most_recent_failure_time = now
        if not connection_failure or status.escalation_level == 0:
            status.escalation_level = min(len(BACKOFF_PERIODS) - 1, status.escalation_level + 1)
        delay = float(retry_after) if retry_after is not None else BACKOFF_PERIODS[status.escalation_level]
        if now - self.startup_at < 300 and retry_after is None:
            delay = min(delay, 300)
        status.disabled_until = now + max(0.0, delay) if delay else None
        status.last_error_category = str(category or "")
        status.last_response_duration = float(duration_ms or 0)
        return self.save(status)

    def record_success(self, indexer_id: str, *, duration_ms: float = 0.0, manual_test: bool = False) -> IndexerStatus:
        status = self.get(indexer_id)
        status.last_success = self.now()
        status.escalation_level = 0 if manual_test else max(0, status.escalation_level - 1)
        status.disabled_until = None
        status.last_error_category = ""
        status.last_response_duration = float(duration_ms or 0)
        return self.save(status)

    def save_clearance(self, indexer_id: str, cookies: list[dict[str, Any]], user_agent: str, *, expiration: float | None = None) -> IndexerStatus:
        status = self.get(indexer_id)
        status.cookies_json = json.dumps(cookies, separators=(",", ":"))
        status.cookies_expiration = expiration
        status.user_agent = str(user_agent or "")
        status.last_challenge_solve = self.now()
        return self.save(status)

    def is_blocked(self, indexer_id: str) -> bool:
        status = self.get(indexer_id)
        return bool(status.disabled_until and status.disabled_until > self.now())

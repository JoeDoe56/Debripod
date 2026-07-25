from __future__ import annotations

# Source anchor: 9a6517fca316fb8ef595cd81ed205266417a2818

import time
from typing import Any

from .database import database


def save_subscription(username: str, client_id: str, subscription: dict[str, Any]) -> None:
    user = str(username or "").strip()
    client = str(client_id or "").strip()
    endpoint = str(subscription.get("endpoint") or "").strip()
    keys = subscription.get("keys") if isinstance(subscription.get("keys"), dict) else {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    if not all((user, client, endpoint, p256dh, auth)):
        raise ValueError("Incomplete push subscription")
    expiration = subscription.get("expirationTime")
    now = time.time()
    with database() as conn:
        conn.execute(
            """INSERT INTO push_subscriptions(username,client_id,endpoint,p256dh,auth,expiration_time,created_at,updated_at,revoked)
            VALUES(?,?,?,?,?,?,?,?,0) ON CONFLICT(username,client_id,endpoint) DO UPDATE SET
            p256dh=excluded.p256dh,auth=excluded.auth,expiration_time=excluded.expiration_time,
            updated_at=excluded.updated_at,revoked=0""",
            (user, client, endpoint, p256dh, auth, expiration, now, now),
        )


def revoke_subscription(username: str, client_id: str, endpoint: str = "") -> int:
    query = "UPDATE push_subscriptions SET revoked=1,updated_at=? WHERE username=? AND client_id=?"
    params: list[Any] = [time.time(), str(username or "").strip(), str(client_id or "").strip()]
    if endpoint:
        query += " AND endpoint=?"
        params.append(str(endpoint).strip())
    with database() as conn:
        cursor = conn.execute(query, params)
        return int(cursor.rowcount or 0)


def subscriptions_for_client(username: str, client_id: str) -> list[dict[str, Any]]:
    user = str(username or "").strip()
    client = str(client_id or "").strip()
    if not user or not client:
        return []
    with database(write=False) as conn:
        rows = conn.execute(
            """SELECT username,client_id,endpoint,p256dh,auth,expiration_time
            FROM push_subscriptions WHERE username=? AND client_id=? AND revoked=0 ORDER BY created_at""",
            (user, client),
        ).fetchall()
    return [dict(row) for row in rows]


def claim_delivery(task_id: str, username: str, client_id: str, event: str, status: str = "scheduled") -> bool:
    if not all(str(value or "").strip() for value in (task_id, username, client_id, event)):
        return False
    try:
        with database() as conn:
            conn.execute(
                """INSERT INTO notification_deliveries(task_id,username,client_id,event,delivered_at,status)
                VALUES(?,?,?,?,?,?)""",
                (str(task_id), str(username), str(client_id), str(event), time.time(), str(status)),
            )
        return True
    except Exception:
        return False


def update_delivery_status(task_id: str, username: str, client_id: str, event: str, status: str) -> None:
    with database() as conn:
        conn.execute(
            """UPDATE notification_deliveries SET delivered_at=?,status=?
            WHERE task_id=? AND username=? AND client_id=? AND event=?""",
            (time.time(), str(status), str(task_id), str(username), str(client_id), str(event)),
        )

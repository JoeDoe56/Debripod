from __future__ import annotations

# Source anchor: 9a6517fca316fb8ef595cd81ed205266417a2818

import base64
import json
import threading
from typing import Any, Callable

from ..storage.push_subscriptions import (
    claim_delivery,
    revoke_subscription,
    subscriptions_for_client,
    update_delivery_status,
)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def vapid_keys() -> tuple[str, str]:
    from ..secrets import get_secret, set_secret

    private_pem = get_secret("global", "VAPID_PRIVATE_KEY")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    if private_pem:
        key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        private_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        set_secret("global", "VAPID_PRIVATE_KEY", private_pem, provider_identity="Web Push VAPID")
    numbers = key.public_key().public_numbers()
    public_key = b"\x04" + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")
    public_text = _b64url(public_key)
    from ..storage.database import database
    import time
    with database() as conn:
        conn.execute(
            """INSERT INTO app_settings(user_id,key,value_json,updated_at)
            VALUES('','vapid_public_key',?,?)
            ON CONFLICT(user_id,key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at""",
            (json.dumps(public_text), time.time()),
        )
    return private_pem, public_text


def _default_sender(subscription: dict[str, Any], payload: str, private_key: str) -> None:
    from pywebpush import webpush

    webpush(
        subscription_info={
            "endpoint": subscription["endpoint"],
            "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
        },
        data=payload,
        vapid_private_key=private_key,
        vapid_claims={"sub": "mailto:debripod@localhost"},
    )


def enqueue_task_completion(task: Any, sender: Callable[[dict[str, Any], str, str], None] | None = None) -> bool:
    task_id = str(getattr(task, "id", "") or "").strip()
    username = str(getattr(task, "owner", "") or "").strip()
    client_id = str(getattr(task, "origin_client_id", "") or "").strip()
    if not task_id or not username or not client_id:
        return False
    subscriptions = subscriptions_for_client(username, client_id)
    if not subscriptions or not claim_delivery(task_id, username, client_id, "done"):
        return False
    payload = json.dumps({
        "title": str(getattr(task, "title", "") or "Task"),
        "body": "Task complete",
        "data": {"task_id": task_id, "url": "/?task=" + task_id},
    }, separators=(",", ":"))

    def deliver() -> None:
        status = "failed"
        try:
            private_key, _public_key = vapid_keys()
            send = sender or _default_sender
            for subscription in subscriptions:
                try:
                    send(subscription, payload, private_key)
                    status = "sent"
                except Exception as exc:
                    response = getattr(exc, "response", None)
                    if int(getattr(response, "status_code", 0) or 0) in {404, 410}:
                        revoke_subscription(username, client_id, str(subscription.get("endpoint") or ""))
            update_delivery_status(task_id, username, client_id, "done", status)
        except Exception:
            update_delivery_status(task_id, username, client_id, "done", status)

    threading.Thread(target=deliver, name="debripod-push", daemon=True).start()
    return True

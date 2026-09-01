from __future__ import annotations

from aiohttp import web

from ..auth import current_user
from ..factory import json_response
from ..Services.push_notifications import vapid_keys
from ..storage.push_subscriptions import revoke_subscription, save_subscription, subscriptions_for_client


def register_notification_routes(app) -> None:
    def user_id(request: web.Request) -> str:
        user = current_user(request)
        return str(getattr(user, "user_id", "") or "").strip()

    async def notifications_public_key(_request: web.Request):
        try:
            _private, public = vapid_keys()
            return json_response(ok=True, public_key=public)
        except Exception:
            return json_response(ok=False, error="Secure notification keys are unavailable.", status=503)

    async def notifications_status(request: web.Request):
        client_id = str(request.headers.get("X-DebriPod-Client-Id") or request.query.get("client_id") or "").strip()
        enabled = bool(subscriptions_for_client(user_id(request), client_id))
        return json_response(ok=True, enabled=enabled, client_id=client_id)

    async def notifications_subscribe(request: web.Request):
        data = await request.json()
        client_id = str(data.get("client_id") or request.headers.get("X-DebriPod-Client-Id") or "").strip()
        try:
            save_subscription(user_id(request), client_id, data.get("subscription") or {})
            return json_response(ok=True)
        except ValueError as exc:
            return json_response(ok=False, error=str(exc), status=400)

    async def notifications_unsubscribe(request: web.Request):
        data = await request.json()
        client_id = str(data.get("client_id") or request.headers.get("X-DebriPod-Client-Id") or "").strip()
        endpoint = str(data.get("endpoint") or "").strip()
        revoke_subscription(user_id(request), client_id, endpoint)
        return json_response(ok=True)

    app.router.add_get("/api/notifications/public-key", notifications_public_key)
    app.router.add_get("/api/notifications/status", notifications_status)
    app.router.add_post("/api/notifications/subscribe", notifications_subscribe)
    app.router.add_post("/api/notifications/unsubscribe", notifications_unsubscribe)

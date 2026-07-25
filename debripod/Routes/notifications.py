from __future__ import annotations

from flask import jsonify, request, session

from ..Services.push_notifications import vapid_keys
from ..storage.push_subscriptions import revoke_subscription, save_subscription, subscriptions_for_client


def register_notification_routes(app) -> None:
    def username() -> str:
        return str(session.get("username") or "").strip()

    @app.route("/api/notifications/public-key", methods=["GET"])
    def notifications_public_key():
        try:
            _private, public = vapid_keys()
            return jsonify(ok=True, public_key=public)
        except Exception:
            return jsonify(ok=False, error="Secure notification keys are unavailable."), 503

    @app.route("/api/notifications/status", methods=["GET"])
    def notifications_status():
        client_id = str(request.headers.get("X-DebriPod-Client-Id") or request.args.get("client_id") or "").strip()
        enabled = bool(subscriptions_for_client(username(), client_id))
        return jsonify(ok=True, enabled=enabled, client_id=client_id)

    @app.route("/api/notifications/subscribe", methods=["POST"])
    def notifications_subscribe():
        data = request.get_json(silent=True) or {}
        client_id = str(data.get("client_id") or request.headers.get("X-DebriPod-Client-Id") or "").strip()
        try:
            save_subscription(username(), client_id, data.get("subscription") or {})
            return jsonify(ok=True)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @app.route("/api/notifications/unsubscribe", methods=["POST"])
    def notifications_unsubscribe():
        data = request.get_json(silent=True) or {}
        client_id = str(data.get("client_id") or request.headers.get("X-DebriPod-Client-Id") or "").strip()
        endpoint = str(data.get("endpoint") or "").strip()
        revoke_subscription(username(), client_id, endpoint)
        return jsonify(ok=True)

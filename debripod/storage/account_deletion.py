from __future__ import annotations

from .database import database


def delete_user_owned_data(user_id: str) -> None:
    """Delete durable user-owned records without touching shared media data."""
    owner = str(user_id or "").strip()
    if not owner:
        raise ValueError("A user ID is required")
    with database() as conn:
        # Child rows must go first because not every historical database had
        # foreign-key enforcement enabled when task data was written.
        conn.execute("DELETE FROM task_files WHERE task_id IN (SELECT task_id FROM tasks WHERE owner_user_id=?)", (owner,))
        conn.execute("DELETE FROM tasks WHERE owner_user_id=?", (owner,))
        conn.execute("DELETE FROM app_settings WHERE user_id=?", (owner,))
        conn.execute("DELETE FROM service_status WHERE user_id=?", (owner,))
        conn.execute("DELETE FROM playback_state WHERE user_id=?", (owner,))
        conn.execute("DELETE FROM search_history WHERE user_id=?", (owner,))
        conn.execute("DELETE FROM media_likes WHERE user_id=?", (owner,))
        conn.execute("DELETE FROM lastfm_loved_tracks WHERE user_id=?", (owner,))
        conn.execute("DELETE FROM push_subscriptions WHERE user_id=?", (owner,))
        conn.execute("DELETE FROM notification_deliveries WHERE user_id=?", (owner,))
        conn.execute("DELETE FROM user_passkeys WHERE user_id=?", (owner,))
        conn.execute("DELETE FROM passkey_challenges WHERE user_id=?", (owner,))
        conn.execute("DELETE FROM auth_sessions WHERE user_id=?", (owner,))


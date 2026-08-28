from __future__ import annotations

import re
import time

import keyring
from keyring.errors import KeyringError, NoKeyringError, PasswordDeleteError

from .storage.database import database

SERVICE_NAME = "DebriPod"
SECRET_SERVICES = {
    "DEBRID_TOKEN", "SOULSEEK_USERNAME", "SOULSEEK_PASSWORD",
    "LASTFM_API_KEY", "LASTFM_API_SECRET", "LASTFM_SESSION_KEY", "APP_SECRET_KEY", "MCP_TOKEN", "VAPID_PRIVATE_KEY",
}


class SecureStorageUnavailable(RuntimeError):
    pass


def _reference(user_id: str, service: str) -> str:
    user = re.sub(r"[^a-z0-9_.-]+", "_", str(user_id or "global").strip().lower()) or "global"
    name = str(service or "").strip().upper()
    if name not in SECRET_SERVICES and not name.startswith("DEBRID_TOKEN:"):
        raise ValueError(f"Unsupported secret service: {service}")
    return f"user:{user}:{name.lower()}"


def _backend_secure() -> None:
    try:
        backend = keyring.get_keyring()
        priority = float(getattr(backend, "priority", 0))
    except Exception as exc:
        raise SecureStorageUnavailable("No operating-system keyring backend is available") from exc
    module = type(backend).__module__.lower()
    if priority <= 0 or "fail" in module or "plaintext" in module:
        raise SecureStorageUnavailable("No secure operating-system keyring backend is available")


def get_secret(user_id: str, service: str) -> str:
    _backend_secure()
    try:
        return keyring.get_password(SERVICE_NAME, _reference(user_id, service)) or ""
    except (KeyringError, NoKeyringError) as exc:
        raise SecureStorageUnavailable("The operating-system keyring could not be read") from exc


def set_secret(user_id: str, service: str, value: str, *, provider_identity: str = "") -> None:
    _backend_secure()
    ref = _reference(user_id, service)
    clean = str(value or "")
    try:
        if clean:
            keyring.set_password(SERVICE_NAME, ref, clean)
        else:
            try:
                keyring.delete_password(SERVICE_NAME, ref)
            except PasswordDeleteError:
                pass
    except (KeyringError, NoKeyringError) as exc:
        raise SecureStorageUnavailable("The operating-system keyring could not save the secret") from exc
    with database() as conn:
        conn.execute("""INSERT INTO service_status(user_id,service,saved,keyring_ref,provider_identity,updated_at)
          VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,service) DO UPDATE SET saved=excluded.saved,
          keyring_ref=excluded.keyring_ref,provider_identity=excluded.provider_identity,updated_at=excluded.updated_at""",
          (str(user_id or ""), str(service), int(bool(clean)), ref, str(provider_identity or ""), time.time()))


def delete_secret(user_id: str, service: str) -> None:
    set_secret(user_id, service, "")


def saved_status(user_id: str) -> dict[str, dict[str, object]]:
    with database(write=False) as conn:
        rows = conn.execute("SELECT service,saved,keyring_ref,provider_identity,updated_at FROM service_status WHERE user_id=?", (str(user_id or ""),)).fetchall()
    return {str(r["service"]): {"saved": bool(r["saved"]), "keyring_ref": str(r["keyring_ref"]),
            "provider_identity": str(r["provider_identity"]), "updated_at": float(r["updated_at"])} for r in rows}

from __future__ import annotations

from typing import Any

from .alldebrid import AllDebridProvider
from .base import DebridAuthError, DebridProviderBase
from .models import DebridProviderSpec
from .premiumize import PremiumizeProvider
from .real_debrid import RealDebridProvider
from .torbox import TorBoxProvider


PROVIDER_SPECS = {
    "real_debrid": DebridProviderSpec("real_debrid", "Real Debrid", "REAL_DEBRID_API_KEY", "RD_BASE"),
    "alldebrid": DebridProviderSpec("alldebrid", "AllDebrid", "ALLDEBRID_API_KEY", "ALLDEBRID_BASE"),
    "premiumize": DebridProviderSpec("premiumize", "Premiumize", "PREMIUMIZE_API_KEY", "PREMIUMIZE_BASE"),
    "torbox": DebridProviderSpec("torbox", "TorBox", "TORBOX_API_KEY", "TORBOX_BASE"),
}


def provider_specs() -> dict[str, DebridProviderSpec]:
    return dict(PROVIDER_SPECS)


def configured_provider_id(settings: dict) -> str:
    provider_id = str((settings or {}).get("DEBRID_PROVIDER") or "").strip().lower()
    spec = PROVIDER_SPECS.get(provider_id)
    if not spec:
        return ""
    return provider_id if str((settings or {}).get(spec.token_setting_key) or "").strip() else ""


def provider_status(settings: dict) -> dict:
    active = configured_provider_id(settings)
    providers: dict[str, dict[str, Any]] = {}
    for provider_id, spec in PROVIDER_SPECS.items():
        configured = bool(str((settings or {}).get(spec.token_setting_key) or "").strip())
        providers[provider_id] = {
            "id": provider_id,
            "label": spec.label,
            "configured": configured,
            "active": provider_id == active,
            "token_key": spec.token_setting_key,
            "base_key": spec.base_setting_key,
        }
    return {"active_provider": active, "configured": bool(active), "providers": providers}


def get_provider(provider_id: str, settings: dict, timeout_seconds: int) -> DebridProviderBase:
    provider_id = str(provider_id or "").strip().lower()
    spec = PROVIDER_SPECS.get(provider_id)
    if not spec:
        raise DebridAuthError("No debrid provider is configured.")
    token = str((settings or {}).get(spec.token_setting_key) or "").strip()
    if not token:
        raise DebridAuthError(f"{spec.label} token is missing.")
    base_url = str((settings or {}).get(spec.base_setting_key) or "").strip()
    if provider_id == "real_debrid":
        return RealDebridProvider(token, base_url, timeout_seconds)
    if provider_id == "alldebrid":
        return AllDebridProvider(token, base_url, timeout_seconds)
    if provider_id == "premiumize":
        return PremiumizeProvider(token, base_url, timeout_seconds, int((settings or {}).get("SEARCH_STREAM_SESSION_TTL_SECONDS") or 3600))
    if provider_id == "torbox":
        return TorBoxProvider(token, base_url, timeout_seconds)
    raise DebridAuthError("No debrid provider is configured.")


def get_active_provider(settings: dict, timeout_seconds: int) -> DebridProviderBase:
    provider_id = configured_provider_id(settings)
    if not provider_id:
        raise DebridAuthError("No debrid provider is configured.")
    return get_provider(provider_id, settings, timeout_seconds)

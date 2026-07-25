from .base import DebridAuthError, DebridProviderBase, DebridProviderError
from .models import DebridFile, DebridPreview, DebridProviderSpec, DebridResolvedLink
_REGISTRY_EXPORTS = {
    "PROVIDER_SPECS",
    "configured_provider_id",
    "get_active_provider",
    "get_provider",
    "provider_specs",
    "provider_status",
}


def __getattr__(name):
    if name in _REGISTRY_EXPORTS:
        from . import registry
        return getattr(registry, name)
    raise AttributeError(name)

__all__ = [
    "DebridAuthError",
    "DebridProviderBase",
    "DebridProviderError",
    "DebridFile",
    "DebridPreview",
    "DebridProviderSpec",
    "DebridResolvedLink",
    "PROVIDER_SPECS",
    "configured_provider_id",
    "get_active_provider",
    "get_provider",
    "provider_specs",
    "provider_status",
]

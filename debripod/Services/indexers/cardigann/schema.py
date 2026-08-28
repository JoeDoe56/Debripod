from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml
from yaml.constructor import SafeConstructor


class _ProwlarrSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that keeps Cardigann identifiers such as 0_0 as strings."""


def _construct_prowlarr_int(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    value = loader.construct_scalar(node)
    return value if "_" in value else SafeConstructor.construct_yaml_int(loader, node)


_ProwlarrSafeLoader.add_constructor("tag:yaml.org,2002:int", _construct_prowlarr_int)


def _known(raw: dict[str, Any], names: set[str]) -> dict[str, Any]:
    return {key: value for key, value in raw.items() if key not in names}


@dataclass(slots=True)
class SettingField:
    name: str
    type: str = "text"
    label: str = ""
    default: Any = None
    required: bool = False
    options: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, name: str, raw: Any) -> "SettingField":
        value = dict(raw or {}) if isinstance(raw, dict) else {"default": raw}
        known = {"type", "label", "default", "required", "options"}
        return cls(name, str(value.get("type") or "text"), str(value.get("label") or name), value.get("default"), bool(value.get("required")), dict(value.get("options") or {}), _known(value, known))

    @property
    def requires_setup(self) -> bool:
        sensitive = self.type.casefold() in {"password", "api_key", "apikey", "cookie", "captcha", "username"}
        missing = self.default in {None, "", False}
        return bool((self.required or sensitive) and missing)


@dataclass(slots=True)
class CardigannDefinition:
    id: str
    name: str
    type: str
    links: list[str]
    settings: list[SettingField]
    caps: dict[str, Any]
    categories: dict[str, Any]
    login: dict[str, Any]
    search: dict[str, Any]
    download: dict[str, Any]
    before: list[dict[str, Any]]
    infohash: dict[str, Any]
    error_selectors: list[Any]
    extra: dict[str, Any] = field(default_factory=dict)
    origin: str = "official"
    parse_error: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, origin: str = "official") -> "CardigannDefinition":
        if not isinstance(raw, dict):
            raise ValueError("Cardigann definition must be a mapping")
        ident = str(raw.get("id") or "").strip()
        if not ident:
            raise ValueError("Cardigann definition is missing id")
        settings_raw = raw.get("settings") or []
        settings: list[SettingField] = []
        if isinstance(settings_raw, dict):
            settings = [SettingField.from_raw(name, value) for name, value in settings_raw.items()]
        elif isinstance(settings_raw, list):
            for item in settings_raw:
                if isinstance(item, dict):
                    name = str(item.get("name") or item.get("id") or "").strip()
                    if name:
                        settings.append(SettingField.from_raw(name, item))
        links = raw.get("links") or ([raw.get("link")] if raw.get("link") else [])
        known = {"id", "name", "type", "links", "link", "settings", "caps", "categories", "login", "search", "download", "before", "infohash", "error", "errors"}
        return cls(
            id=ident,
            name=str(raw.get("name") or ident),
            type=str(raw.get("type") or "public").casefold(),
            links=[str(link) for link in links if str(link)],
            settings=settings,
            caps=dict(raw.get("caps") or {}),
            categories=dict(raw.get("categories") or {}),
            login=dict(raw.get("login") or {}),
            search=dict(raw.get("search") or {}),
            download=dict(raw.get("download") or {}),
            before=list(raw.get("before") or []),
            infohash=dict(raw.get("infohash") or {}),
            error_selectors=list(raw.get("errors") or raw.get("error") or []),
            extra=_known(raw, known),
            origin=origin,
        )

    @classmethod
    def from_yaml(cls, text: str, *, origin: str = "official") -> "CardigannDefinition":
        value = yaml.load(text, Loader=_ProwlarrSafeLoader)
        return cls.from_dict(value, origin=origin)

    @property
    def requires_setup(self) -> bool:
        return self.type != "public" or bool(self.login) or any(item.requires_setup for item in self.settings)

    @property
    def eligible(self) -> bool:
        return self.type == "public" and bool(self.search) and bool(self.links) and not self.requires_setup

    def metadata(self) -> dict[str, Any]:
        return {
            "id": self.id, "label": self.name, "type": self.type, "origin": self.origin,
            "requires_setup": self.requires_setup, "eligible": self.eligible, "parse_error": self.parse_error,
            "settings_fields": [
                {"name": item.name, "type": item.type, "label": item.label, "required": item.required, "default": item.default, "options": item.options}
                for item in self.settings
            ],
        }


# Logical aliases make the model vocabulary explicit while retaining raw YAML
# for the portions Cardigann evolves independently.
DefinitionMetadata = CardigannDefinition
Capabilities = dict[str, Any]
CategoryMappings = dict[str, Any]
LoginModel = dict[str, Any]
SearchModel = dict[str, Any]
SearchPath = dict[str, Any]
RowsModel = dict[str, Any]
FieldSelector = dict[str, Any]
FilterModel = dict[str, Any]
DownloadModel = dict[str, Any]
BeforeRequest = dict[str, Any]
InfoHashExtraction = dict[str, Any]
ErrorSelector = dict[str, Any]

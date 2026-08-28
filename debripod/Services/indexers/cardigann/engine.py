from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from urllib.parse import quote, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from .parser import ParseResult, parse_response
from .schema import CardigannDefinition
from .template import render_template


@dataclass(slots=True)
class RequestSpec:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    data: Any = None
    encoding: str = "utf-8"
    delay_seconds: float = 0.0
    tier: int = 0
    parse_config: dict[str, Any] = field(default_factory=dict)
    base_url: str = ""
    preflight: bool = False
    follow_redirects: bool = True


class CardigannEngine:
    def __init__(self, definition: CardigannDefinition, *, config: dict[str, Any] | None = None):
        self.definition = definition
        defaults = {item.name: item.default for item in definition.settings if item.default is not None}
        self.config = {**defaults, **dict(config or {})}
        self.base_url = definition.links[0].rstrip("/") + "/" if definition.links else ""

    def _variables(self, query: str, categories: list[Any], base_url: str | None = None) -> dict[str, Any]:
        now = datetime.now()
        active_base = (base_url or self.base_url).rstrip("/") + "/"
        config = dict(self.config)
        config.setdefault("sitelink", active_base)
        query_model = {
            "Query": query, "Keywords": query, "Categories": categories, "Type": "search",
            "IMDBID": "", "IMDBIDShort": "", "TMDBID": "", "Season": "", "Ep": "",
        }
        return {
            "Query": query_model, "Keywords": query, "Categories": categories, "Config": config,
            "Url": {"Base": active_base}, "Today": {"Year": now.year}, "CurrentYear": now.year,
            "True": True, "False": False,
        }

    @staticmethod
    def _render_inputs(inputs: dict[str, Any], variables: dict[str, Any]) -> tuple[dict[str, Any], str]:
        rendered: dict[str, Any] = {}
        raw_parts: list[str] = []
        for name, value in inputs.items():
            declared_raw = name == "$raw"
            if isinstance(value, dict):
                declared_raw = declared_raw or bool(value.get("raw"))
                value = value.get("value", "")
            resolved = render_template(value, variables)
            if declared_raw:
                if resolved:
                    raw_parts.append(resolved.strip("?&"))
            else:
                rendered[name] = resolved
        return rendered, "&".join(item for item in raw_parts if item)

    def _request_from_model(self, model: dict[str, Any], variables: dict[str, Any], *, tier: int, parse_config: dict[str, Any], base_url: str, preflight: bool = False) -> RequestSpec:
        path_template = model.get("path") or model.get("url") or ""
        rendered_path = render_template(path_template, variables)
        url = urljoin(base_url, rendered_path)
        method = render_template(model.get("method") or "GET", variables).upper()
        inherited = {} if preflight else dict(self.definition.search.get("inputs") or {})
        inherited.update(model.get("inputs") or {})
        rendered_inputs, raw_input = self._render_inputs(inherited, variables)
        separator = str(model.get("queryseparator") or model.get("query_separator") or "&")
        encoding = str(model.get("encoding") or self.definition.extra.get("encoding") or "utf-8")
        data: Any = None
        if method == "GET":
            encoded = urlencode(rendered_inputs, doseq=True, encoding=encoding)
            query = separator.join(item for item in (raw_input, encoded.replace("&", separator)) if item)
            if query:
                url += ("&" if "?" in url else "?") + query
        else:
            if raw_input:
                encoded = urlencode(rendered_inputs, doseq=True, encoding=encoding)
                data = "&".join(item for item in (raw_input, encoded) if item)
            else:
                data = rendered_inputs
        search_headers = {} if preflight else self.definition.search.get("headers") or {}
        headers = {str(name): render_template(value, variables) for name, value in {**search_headers, **(model.get("headers") or {})}.items()}
        request_delay = model.get("requestDelay")
        if request_delay is None:
            request_delay = self.definition.search.get("requestDelay", self.definition.extra.get("requestDelay", 0))
        follow_redirects = bool(model.get("followredirect", self.definition.extra.get("followredirect", True)))
        return RequestSpec(method, url, headers, data, encoding, float(request_delay or 0), tier, parse_config, base_url, preflight, follow_redirects)

    def generate_search_requests(self, query: str, categories: list[Any] | None = None) -> list[RequestSpec]:
        if self.definition.requires_setup:
            raise PermissionError("requires_setup")
        categories = list(categories or [])
        paths = self.definition.search.get("paths") or []
        if isinstance(paths, dict):
            paths = [paths]
        output: list[RequestSpec] = []
        seen: set[tuple[str, str, str]] = set()
        bases = [str(link).rstrip("/") + "/" for link in self.definition.links if str(link)] or [self.base_url]
        for mirror_index, base_url in enumerate(bases):
            variables = self._variables(query, categories, base_url)
            for before in self.definition.before:
                if isinstance(before, dict):
                    spec = self._request_from_model(before, variables, tier=mirror_index * 1000 - 1, parse_config={}, base_url=base_url, preflight=True)
                    key = (spec.method, spec.url, repr(spec.data))
                    if key not in seen:
                        seen.add(key)
                        output.append(spec)
            for index, path in enumerate(paths):
                if isinstance(path, str):
                    path = {"path": path}
                if not isinstance(path, dict):
                    continue
                parse_config = {**self.definition.search, **path}
                parse_config.pop("paths", None)
                tier = mirror_index * 1000 + int(path.get("tier") or index)
                spec = self._request_from_model(path, variables, tier=tier, parse_config=parse_config, base_url=base_url)
                key = (spec.method, spec.url, repr(spec.data))
                if key in seen:
                    continue
                seen.add(key)
                output.append(spec)
        return output

    def parse(self, response: Any, path: dict[str, Any] | RequestSpec | None = None, *, query: str = "", categories: list[Any] | None = None) -> ParseResult:
        config = path.parse_config if isinstance(path, RequestSpec) else path or self.definition.search
        if not config.get("rows"):
            paths = self.definition.search.get("paths") or []
            if isinstance(paths, dict):
                paths = [paths]
            config = next((item for item in paths if isinstance(item, dict) and item.get("rows")), config)
            if self.definition.search.get("response") and not config.get("response"):
                config = {**config, "response": self.definition.search.get("response")}
        content_type = str(getattr(response, "headers", {}).get("Content-Type", "text/html"))
        return parse_response(getattr(response, "text", ""), content_type, config, definition_id=self.definition.id, status_code=int(getattr(response, "status_code", 200)), variables=self._variables(query, list(categories or [])))

    @staticmethod
    def magnet_for_hash(infohash: str, title: str = "") -> str:
        value = str(infohash or "").strip().lower()
        return f"magnet:?xt=urn:btih:{value}" + (("&dn=" + quote(title, safe="")) if title else "")

    def resolve_download(self, release: dict[str, Any], fetch: Callable[[RequestSpec], Any]) -> dict[str, Any]:
        url = str(release.get("magnet") or release.get("download") or release.get("link") or "")
        infohash = str(release.get("infohash") or "").lower()
        if url.startswith("magnet:"):
            return {"magnet": url, "infohash": infohash, "torrent": b""}
        if infohash and not url:
            return {"magnet": self.magnet_for_hash(infohash, str(release.get("title") or "")), "infohash": infohash, "torrent": b""}
        current = urljoin(self.base_url, self._replace_legacy_link(url))
        for _redirect in range(6):
            response = fetch(RequestSpec("GET", current))
            location = str(getattr(response, "headers", {}).get("Location", ""))
            if 300 <= int(getattr(response, "status_code", 200)) < 400 and location:
                if location.startswith("magnet:"):
                    return {"magnet": location, "infohash": infohash, "torrent": b""}
                current = urljoin(current, location)
                continue
            selected = self._download_link(response)
            if selected:
                if selected.startswith("magnet:"):
                    return {"magnet": selected, "infohash": self._magnet_hash(selected) or infohash, "torrent": b""}
                if urljoin(current, selected) != current:
                    current = urljoin(current, selected)
                    continue
            extracted = self._download_infohash(response)
            if extracted:
                return {"magnet": self.magnet_for_hash(extracted, str(release.get("title") or "")), "infohash": extracted.lower(), "torrent": b""}
            content = bytes(getattr(response, "content", b""))
            if not content.startswith(b"d") or b"pieces" not in content:
                raise ValueError("download response is not a valid torrent")
            return {"magnet": "", "infohash": infohash, "torrent": content}
        raise ValueError("download exceeded five redirects")

    def _replace_legacy_link(self, url: str) -> str:
        legacy = self.definition.extra.get("legacylinks") or []
        for old in legacy if isinstance(legacy, list) else [legacy]:
            old = str(old or "").rstrip("/") + "/"
            if old != "/" and str(url).startswith(old):
                return self.base_url + str(url)[len(old):]
        return str(url)

    @staticmethod
    def _magnet_hash(value: str) -> str:
        import re
        match = re.search(r"urn:btih:([A-Za-z0-9]{32,40})", str(value or ""), re.I)
        return match.group(1).lower() if match else ""

    def _download_link(self, response: Any) -> str:
        selectors = self.definition.download.get("selectors") or []
        if isinstance(selectors, dict):
            selectors = [selectors]
        if not selectors:
            return ""
        soup = BeautifulSoup(str(getattr(response, "text", "") or ""), "html.parser")
        variables = self._variables("", [])
        for spec in selectors:
            if not isinstance(spec, dict):
                continue
            selector = render_template(spec.get("selector") or "", variables)
            node = soup.select_one(selector) if selector else None
            if node is not None:
                return str(node.get(str(spec.get("attribute") or "href"), "") or node.get_text(" ", strip=True))
        return ""

    def _download_infohash(self, response: Any) -> str:
        model = self.definition.download.get("infohash") or self.definition.infohash
        if not isinstance(model, dict):
            return ""
        spec = model.get("hash") if isinstance(model.get("hash"), dict) else model
        selector = str(spec.get("selector") or "")
        if not selector:
            return ""
        soup = BeautifulSoup(str(getattr(response, "text", "") or ""), "html.parser")
        node = soup.select_one(selector)
        if node is None:
            return ""
        value = node.get(str(spec.get("attribute") or "href"), "") if spec.get("attribute") else node.get_text(" ", strip=True)
        from .filters import apply_filters
        return str(apply_filters(value, spec.get("filters"), definition_id=self.definition.id, field="infohash") or "")

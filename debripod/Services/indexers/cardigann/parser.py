from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from .filters import DefinitionCompatibilityError, apply_filters
from .template import render_template


@dataclass(slots=True)
class ParseResult:
    releases: list[dict[str, Any]] = field(default_factory=list)
    no_results: bool = False
    error_classification: str = ""
    diagnostic_summary: str = ""
    response_content_type: str = ""


def _groups(rows: Any) -> list[dict[str, Any]]:
    if isinstance(rows, list):
        return [item for item in rows if isinstance(item, dict)]
    return [rows] if isinstance(rows, dict) else []


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _field_cases(spec: dict[str, Any]) -> list[dict[str, Any]]:
    cases = spec.get("case") or spec.get("cases")
    if isinstance(cases, list):
        return [dict(item) for item in cases if isinstance(item, dict)] + [spec]
    return [spec]


def _render_value(value: Any, variables: dict[str, Any], result: dict[str, Any]) -> Any:
    if not isinstance(value, str) or "{{" not in value:
        return value
    return render_template(value, {**variables, "Result": result})


def _render_filters(filters: Any, variables: dict[str, Any], result: dict[str, Any]) -> Any:
    rendered: list[Any] = []
    for spec in filters or []:
        if not isinstance(spec, dict):
            rendered.append(spec)
            continue
        item = dict(spec)
        if "args" in item:
            values = item["args"] if isinstance(item["args"], list) else [item["args"]]
            item["args"] = [_render_value(value, variables, result) for value in values]
        rendered.append(item)
    return rendered


def _html_case(value: Any, node: Any, row: Any, cases: Any) -> Any:
    if not isinstance(cases, dict):
        return value
    fallback = value
    for selector, mapped in cases.items():
        selector = str(selector or "")
        if selector == "*":
            fallback = mapped
            continue
        if selector.startswith(":contains("):
            needle = selector[len(":contains("):].rstrip(")").strip("\"'")
            if needle in node.get_text(" ", strip=True):
                return mapped
            continue
        try:
            if node.select_one(selector) is not None or row.select_one(selector) is not None:
                return mapped
        except Exception:
            continue
    return fallback


def _html_value(row: Any, spec: Any, *, definition_id: str, field_name: str, variables: dict[str, Any], result: dict[str, Any]) -> Any:
    if not isinstance(spec, dict):
        return spec
    for selected in _field_cases(spec):
        if "text" in selected:
            value = _render_value(selected.get("text"), variables, result)
            return apply_filters(value, _render_filters(selected.get("filters"), variables, result), definition_id=definition_id, field=field_name)
        selector = _render_value(selected.get("selector"), variables, result)
        node = row.select_one(str(selector)) if selector else row
        if node is None:
            continue
        removals = selected.get("remove") or selected.get("remove_selectors") or []
        if isinstance(removals, str):
            removals = [removals]
        for remove in removals:
            for child in node.select(str(remove)):
                child.decompose()
        attribute = selected.get("attribute")
        if attribute:
            if not node.has_attr(str(attribute)):
                if selected.get("optional"):
                    return selected.get("default", "")
                continue
            value: Any = node.get(str(attribute), "")
        elif selected.get("html"):
            value = node.decode_contents()
        else:
            value = node.get_text(" ", strip=True)
        if (value is None or value == "") and "default" in selected:
            value = _render_value(selected["default"], variables, result)
        value = apply_filters(value, _render_filters(selected.get("filters"), variables, result), definition_id=definition_id, field=field_name)
        return _html_case(value, node, row, selected.get("case") or selected.get("cases"))
    if spec.get("optional"):
        return _render_value(spec.get("default", ""), variables, result)
    return _render_value(spec.get("default", ""), variables, result)


def parse_html(content: str, search: dict[str, Any], *, definition_id: str = "", status_code: int = 200, content_type: str = "text/html", variables: dict[str, Any] | None = None, parser: str = "html.parser") -> ParseResult:
    variables = dict(variables or {})
    markup = content or ""
    if parser == "xml":
        # html.parser is always available, unlike optional lxml. Protect XML
        # elements that HTML treats specially, then restore the selector name
        # expected by Cardigann after the tree is built.
        markup = re.sub(r"<(/?)title(?=[\s>])", r"<\1raw_title", markup, flags=re.I)
        markup = re.sub(r"<(/?)link(?=[\s>])", r"<\1raw_link", markup, flags=re.I)
    with warnings.catch_warnings():
        if parser == "xml":
            warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(markup, "html.parser")
    if parser == "xml":
        for node in soup.find_all("raw_link"):
            node.name = "link"
    for error in search.get("error") or search.get("errors") or []:
        spec = error if isinstance(error, dict) else {"selector": error}
        node = soup.select_one(str(spec.get("selector") or ""))
        if node is not None:
            return ParseResult([], False, str(spec.get("category") or "definition_error"), node.get_text(" ", strip=True)[:300], content_type)
    no_result_selectors = search.get("noResults") or search.get("no_results") or []
    if isinstance(no_result_selectors, (str, dict)):
        no_result_selectors = [no_result_selectors]
    for item in no_result_selectors:
        selector = item.get("selector") if isinstance(item, dict) else item
        if selector and soup.select_one(str(selector)) is not None:
            return ParseResult([], True, "no_results", "definition no-results selector matched", content_type)
    releases: list[dict[str, Any]] = []
    for group in _groups(search.get("rows")):
        selector = str(group.get("selector") or "")
        if not selector:
            continue
        fields = group.get("fields") or search.get("fields") or {}
        for row in soup.select(selector):
            release: dict[str, Any] = {}
            for name, spec in fields.items():
                release[name] = _html_value(row, spec, definition_id=definition_id, field_name=str(name), variables=variables, result=release)
            if any(_present(value) for value in release.values()):
                releases.append(release)
    if releases:
        return ParseResult(releases, False, "", f"parsed {len(releases)} release rows", content_type)
    return ParseResult([], False, "layout_changed", "row selectors produced no releases", content_type)


@dataclass(slots=True)
class _JsonRow:
    value: Any
    parent: Any = None


def _json_select(value: Any, selector: str) -> Any:
    parent = value.parent if isinstance(value, _JsonRow) else None
    current = value.value if isinstance(value, _JsonRow) else value
    selector = str(selector or "")
    if selector.startswith(".."):
        current = parent
        selector = selector[2:].lstrip(".")
    for part in selector.split("."):
        if not part:
            continue
        if part == "*":
            return current if isinstance(current, list) else []
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)] if int(part) < len(current) else None
        else:
            return None
    return current


def _json_value(row: Any, spec: Any, *, definition_id: str, field_name: str, variables: dict[str, Any], result: dict[str, Any]) -> Any:
    if not isinstance(spec, dict):
        return spec
    if "text" in spec:
        value = _render_value(spec.get("text"), variables, result)
    else:
        value = _json_select(row, str(spec.get("selector") or "")) if spec.get("selector") else (row.value if isinstance(row, _JsonRow) else row)
    if spec.get("has") and not _present(_json_select(row, str(spec["has"]))):
        return spec.get("default", "")
    if spec.get("not") and bool(_json_select(row, str(spec["not"]))):
        return spec.get("default", "")
    if "contains" in spec and str(spec["contains"]) not in str(value or ""):
        return spec.get("default", "")
    if value is None or value == "":
        value = _render_value(spec.get("default", ""), variables, result)
    value = apply_filters(value, _render_filters(spec.get("filters"), variables, result), definition_id=definition_id, field=field_name)
    cases = spec.get("case") or spec.get("cases")
    if isinstance(cases, dict):
        value = cases.get(value, cases.get(str(value), cases.get("*", value)))
    return value


def parse_json(content: str | bytes | dict[str, Any] | list[Any], search: dict[str, Any], *, definition_id: str = "", status_code: int = 200, content_type: str = "application/json", variables: dict[str, Any] | None = None) -> ParseResult:
    variables = dict(variables or {})
    try:
        payload = json.loads(content) if isinstance(content, (str, bytes)) else content
    except json.JSONDecodeError as exc:
        return ParseResult([], False, "definition_error", f"malformed JSON: {exc}", content_type)
    releases: list[dict[str, Any]] = []
    for group in _groups(search.get("rows")):
        selector = render_template(group.get("selector") or "", variables)
        rows = _json_select(payload, selector.lstrip("$").lstrip("."))
        if isinstance(rows, dict):
            rows = [rows]
        if group.get("attribute") and isinstance(rows, list):
            expanded: list[_JsonRow] = []
            attribute = str(group.get("attribute") or "")
            for parent in rows:
                children = _json_select(parent, attribute)
                if isinstance(children, list):
                    expanded.extend(_JsonRow(child, parent) for child in children)
                elif children is not None:
                    expanded.append(_JsonRow(children, parent))
            rows = expanded
        fields = group.get("fields") or search.get("fields") or {}
        for row in rows if isinstance(rows, list) else []:
            if group.get("has") and not _present(_json_select(row, str(group["has"]))):
                continue
            if group.get("not") and bool(_json_select(row, str(group["not"]))):
                continue
            if group.get("contains") and str(group["contains"]) not in str(row):
                continue
            release: dict[str, Any] = {}
            for name, spec in fields.items():
                release[name] = _json_value(row, spec, definition_id=definition_id, field_name=str(name), variables=variables, result=release)
            if any(_present(value) for value in release.values()):
                releases.append(release)
    if releases:
        return ParseResult(releases, False, "", f"parsed {len(releases)} release rows", content_type)
    no_results = bool(search.get("emptyIsNoResults") or search.get("empty_is_no_results"))
    return ParseResult([], no_results, "no_results" if no_results else "layout_changed", "JSON rows were empty", content_type)


def parse_response(content: Any, content_type: str, search: dict[str, Any], *, definition_id: str = "", status_code: int = 200, variables: dict[str, Any] | None = None) -> ParseResult:
    if status_code >= 400:
        return ParseResult([], False, "http_error", f"HTTP {status_code}", content_type)
    response_model = search.get("response") or ""
    response_type = response_model.get("type", "") if isinstance(response_model, dict) else response_model
    if "json" in str(content_type).casefold() or str(response_type).casefold() == "json":
        return parse_json(content, search, definition_id=definition_id, status_code=status_code, content_type=content_type, variables=variables)
    if "xml" in str(content_type).casefold() or str(response_type).casefold() == "xml":
        return parse_html(str(content or ""), search, definition_id=definition_id, status_code=status_code, content_type=content_type, variables=variables, parser="xml")
    return parse_html(str(content or ""), search, definition_id=definition_id, status_code=status_code, content_type=content_type, variables=variables)

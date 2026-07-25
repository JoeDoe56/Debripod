from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def normalize_identifier(value: Any) -> str | None:
    if value is None or isinstance(value, (list, dict, set, tuple)):
        return None
    text = str(value).strip()
    return text if text else None


def first_identifier(payload: Mapping[str, Any] | None, *keys: str) -> str | None:
    source = payload if isinstance(payload, Mapping) else {}
    for key in keys:
        if key not in source:
            continue
        normalized = normalize_identifier(source[key])
        if normalized is not None:
            return normalized
    return None


def normalize_identifier_list(values: Iterable[Any] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        normalized = normalize_identifier(value)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def identifiers_equal(left: Any, right: Any) -> bool:
    normalized_left = normalize_identifier(left)
    normalized_right = normalize_identifier(right)
    return normalized_left is not None and normalized_left == normalized_right

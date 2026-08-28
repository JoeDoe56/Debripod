from __future__ import annotations

import html
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse


class DefinitionCompatibilityError(ValueError):
    pass


def _timeago(value: str) -> datetime:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(second|minute|hour|day|week|month|year)s?", value, re.I)
    if not match:
        raise ValueError(f"cannot parse relative time: {value}")
    amount = float(match.group(1))
    unit = match.group(2).casefold()
    seconds = amount * {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800, "month": 2592000, "year": 31536000}[unit]
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


def _date_format(value: str) -> str:
    mapping = {
        "yyyy": "%Y", "yyy": "%Y", "yy": "%y", "y": "%y",
        "MMMM": "%B", "MMM": "%b", "MM": "%m", "M": "%m",
        "dddd": "%A", "ddd": "%a", "dd": "%d", "d": "%d",
        "HH": "%H", "H": "%H", "hh": "%I", "h": "%I",
        "mm": "%M", "m": "%M", "ss": "%S", "s": "%S",
        "tt": "%p", "zzz": "%z", "zz": "%z", "z": "%z", "K": "%z",
    }
    tokens = re.compile("|".join(sorted(map(re.escape, mapping), key=len, reverse=True)))
    output: list[str] = []
    index = 0
    quoted = False
    while index < len(value):
        if value[index] == "'":
            quoted = not quoted
            index += 1
            continue
        if quoted:
            output.append(value[index])
            index += 1
            continue
        match = tokens.match(value, index)
        if match:
            output.append(mapping[match.group(0)])
            index = match.end()
        else:
            output.append(value[index])
            index += 1
    return "".join(output)


def _regex_pattern(value: Any) -> str:
    pattern = str(value)
    replacements = {
        r"\p{IsCJKUnifiedIdeographs}": r"\u4e00-\u9fff",
        r"\p{L}": r"A-Za-z", r"\p{N}": r"0-9",
        r"\P{L}": r"[^A-Za-z]", r"\P{N}": r"[^0-9]",
    }
    for source, target in replacements.items():
        pattern = pattern.replace(source, target)
    return pattern


def apply_filter(value: Any, name: str, args: list[Any] | None = None, *, definition_id: str = "", field: str = "", logger: logging.Logger | None = None) -> Any:
    args = list(args or [])
    clean = str(name or "").casefold().replace("-", "").replace("_", "")
    text = "" if value is None else str(value)
    if clean == "querystring":
        key = str(args[0]) if args else ""
        return (parse_qs(urlparse(text).query).get(key) or [""])[0]
    if clean in {"timeparse", "dateparse"}:
        formats = [str(item) for item in args] or ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d %b %Y", "%b %d, %Y"]
        for fmt in formats:
            if "%" not in fmt:
                fmt = _date_format(fmt)
            try:
                parsed = datetime.strptime(text.strip(), fmt)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        raise ValueError(f"cannot parse date: {text}")
    if clean == "regexp":
        match = re.search(_regex_pattern(args[0]), text, re.I if len(args) < 2 or args[1] else 0)
        if not match:
            return ""
        group = int(args[1]) if len(args) > 1 and str(args[1]).isdigit() else 1 if match.groups() else 0
        return match.group(group)
    if clean == "rereplace":
        replacement = re.sub(r"\$(\d+)", r"\\g<\1>", str(args[1]) if len(args) > 1 else "")
        return re.sub(_regex_pattern(args[0]), replacement, text)
    if clean == "split":
        parts = text.split(str(args[0]) if args else None)
        return parts[int(args[1])] if len(args) > 1 else parts
    if clean == "replace":
        return text.replace(str(args[0]), str(args[1]) if len(args) > 1 else "")
    if clean == "trim":
        return text.strip(str(args[0]) if args else None)
    if clean == "prepend":
        return str(args[0] if args else "") + text
    if clean == "append":
        return text + str(args[0] if args else "")
    if clean == "tolower":
        return text.lower()
    if clean == "toupper":
        return text.upper()
    if clean == "urldecode":
        return unquote(text)
    if clean == "urlencode":
        return quote(text, safe="")
    if clean == "htmldecode":
        return html.unescape(text)
    if clean == "htmlencode":
        return html.escape(text)
    if clean in {"timeago", "reltime", "fuzzytime"}:
        return _timeago(text)
    if clean == "validfilename":
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text).strip(" .")
    if clean == "diacritics":
        return "".join(char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char))
    if clean == "jsonjoinarray":
        parsed = json.loads(text) if isinstance(value, str) else value
        return str(args[0] if args else ",").join(str(item) for item in (parsed or []))
    if clean == "validate":
        pattern = _regex_pattern(args[0]) if args else ".+"
        if not re.search(pattern, text):
            raise ValueError(f"validation failed for {field or 'field'}")
        return value
    if clean == "andmatch":
        patterns = args or []
        return value if all(re.search(_regex_pattern(pattern), text, re.I) for pattern in patterns) else ""
    if clean in {"hexdump", "strdump"}:
        if logger:
            logger.debug("Cardigann debug filter %s for %s.%s (length=%d)", clean, definition_id, field, len(text))
        return value
    raise DefinitionCompatibilityError(f"Definition {definition_id or '<unknown>'} field {field or '<unknown>'} uses unsupported filter {name}")


def apply_filters(value: Any, filters: list[Any] | None, *, definition_id: str = "", field: str = "", logger: logging.Logger | None = None) -> Any:
    current = value
    for spec in filters or []:
        if isinstance(spec, str):
            name, args = spec, []
        elif isinstance(spec, dict):
            name = str(spec.get("name") or spec.get("type") or next(iter(spec), ""))
            raw_args = spec.get("args", spec.get(name, []))
            args = raw_args if isinstance(raw_args, list) else [raw_args]
        else:
            raise DefinitionCompatibilityError(f"Definition {definition_id} field {field} has malformed filter")
        current = apply_filter(current, name, args, definition_id=definition_id, field=field, logger=logger)
    return current

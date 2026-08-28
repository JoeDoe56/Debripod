from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Mapping


ROMAN_NUMERALS = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6",
    "vii": "7", "viii": "8", "ix": "9", "x": "10", "xi": "11", "xii": "12",
    "xiii": "13", "xiv": "14", "xv": "15", "xvi": "16", "xvii": "17",
    "xviii": "18", "xix": "19", "xx": "20",
}
FORMAT_NOISE = {
    "official", "audio", "video", "lyrics", "lyric", "visualizer", "remaster", "remastered",
    "deluxe", "explicit", "clean", "full", "proper", "repack", "extended", "edition",
    "1080p", "2160p", "720p", "480p", "4k", "hdr", "dv", "bluray", "brrip", "webrip",
    "webdl", "web", "dl", "hdtv", "x264", "x265", "h264", "h265", "hevc", "av1",
    "aac", "mp3", "flac", "m4a", "opus", "dts", "atmos", "lossless", "yify", "rarbg",
}
LOW_INFORMATION = {"a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with"}
_EPISODE_RE = re.compile(r"\bs\s*0*(\d{1,3})\s*e\s*0*(\d{1,4})\b", re.I)
_SEASON_RE = re.compile(r"\bs(?:eason)?\s*0*(\d{1,3})\b", re.I)
_EP_ONLY_RE = re.compile(r"\be(?:pisode)?\s*0*(\d{1,4})\b", re.I)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


@dataclass(frozen=True, slots=True)
class MatchAssessment:
    confidence: float
    code: str
    unrelated: bool
    token_overlap: int
    weighted_coverage: float
    similarity: float


def normalize_text(value: Any, *, remove_format_noise: bool = False) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = text.replace("'", "").replace("`", "")
    words = re.findall(r"[a-z0-9]+", text)
    normalized = [ROMAN_NUMERALS.get(word, word) for word in words]
    if remove_format_noise:
        normalized = [word for word in normalized if word not in FORMAT_NOISE]
    return " ".join(normalized)


normalize_search_text = normalize_text


def tokens(value: Any, *, significant_only: bool = False, remove_format_noise: bool = True) -> list[str]:
    values = normalize_text(value, remove_format_noise=remove_format_noise).split()
    if significant_only:
        return [token for token in values if _token_weight(token) >= 1.0]
    return values


def _token_weight(token: str) -> float:
    if _YEAR_RE.fullmatch(token) or re.fullmatch(r"s?\d+e\d+|\d+", token):
        return 1.0
    if len(token) <= 2 or token in LOW_INFORMATION:
        return 0.15
    return 1.0


def weighted_token_coverage(query: Any, candidate: Any) -> float:
    query_tokens = list(dict.fromkeys(tokens(query)))
    candidate_tokens = set(tokens(candidate))
    total = sum(_token_weight(token) for token in query_tokens)
    present = sum(_token_weight(token) for token in query_tokens if token in candidate_tokens)
    return present / total if total else 0.0


def extract_season_episode(value: Any) -> tuple[int | None, int | None]:
    raw = str(value or "")
    both = _EPISODE_RE.search(raw)
    if both:
        return int(both.group(1)), int(both.group(2))
    normalized = normalize_text(raw)
    compact = re.search(r"\bs\s*0*(\d{1,3})\s*e\s*0*(\d{1,4})\b", normalized)
    if compact:
        return int(compact.group(1)), int(compact.group(2))
    season = _SEASON_RE.search(raw)
    episode = _EP_ONLY_RE.search(raw)
    return (int(season.group(1)) if season else None, int(episode.group(1)) if episode else None)


def extract_years(value: Any) -> set[int]:
    return {int(year) for year in _YEAR_RE.findall(normalize_text(value))}


def _result_mapping(result: Mapping[str, Any] | Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        result = result.to_dict()
    return dict(result or {})


def build_search_blob(result: Mapping[str, Any] | Any) -> str:
    raw = _result_mapping(result)
    provider = raw.get("provider_data") if isinstance(raw.get("provider_data"), dict) else {}
    values = [
        raw.get("title"), raw.get("subtitle"), raw.get("artist"), raw.get("album"), raw.get("year"),
        raw.get("stable_source_id"), raw.get("canonical_url"), provider.get("directory"), provider.get("category"),
    ]
    return normalize_text(" ".join(str(value or "") for value in values), remove_format_noise=True)


def _structured_exact(query: str, raw: dict[str, Any], candidate: str) -> bool:
    query_season, query_episode = extract_season_episode(query)
    candidate_season, candidate_episode = extract_season_episode(candidate)
    query_years = extract_years(query)
    candidate_years = extract_years(candidate)
    query_significant = set(tokens(query, significant_only=True))
    candidate_significant = set(tokens(candidate, significant_only=True))
    textual = {
        token for token in query_significant
        if not re.fullmatch(r"s?\d+e\d+|s\d+|e\d+", token)
    }
    if query_season is not None and query_episode is not None:
        return query_season == candidate_season and query_episode == candidate_episode and bool(textual & candidate_significant)
    if query_years and query_years <= candidate_years:
        without_years = {token for token in query_significant if not _YEAR_RE.fullmatch(token)}
        return bool(without_years) and without_years <= candidate_significant
    stable = normalize_text(raw.get("stable_source_id") or "")
    return bool(stable and normalize_text(query) == stable)


def assess_match(query: Any, result: Mapping[str, Any] | Any) -> MatchAssessment:
    raw = _result_mapping(result)
    normalized_query = normalize_text(query, remove_format_noise=True)
    title = normalize_text(raw.get("title") or "", remove_format_noise=True)
    artist_title = normalize_text(f"{raw.get('artist') or ''} {raw.get('title') or ''}", remove_format_noise=True)
    title_artist = normalize_text(f"{raw.get('title') or ''} {raw.get('artist') or ''}", remove_format_noise=True)
    album_artist = normalize_text(f"{raw.get('album') or ''} {raw.get('artist') or ''}", remove_format_noise=True)
    artist_album = normalize_text(f"{raw.get('artist') or ''} {raw.get('album') or ''}", remove_format_noise=True)
    candidate = str(raw.get("search_blob") or "").strip() or build_search_blob(raw)
    exact_candidates = {value for value in (title, artist_title, title_artist, album_artist, artist_album) if value}
    if normalized_query and normalized_query in exact_candidates:
        return MatchAssessment(1.0, "exact", False, len(tokens(query, significant_only=True)), 1.0, 1.0)
    if _structured_exact(str(query or ""), raw, candidate):
        return MatchAssessment(0.98, "structured", False, len(tokens(query, significant_only=True)), 1.0, 1.0)

    query_tokens = list(dict.fromkeys(tokens(query)))
    significant = list(dict.fromkeys(tokens(query, significant_only=True)))
    candidate_tokens = set(tokens(candidate))
    present_significant = [token for token in significant if token in candidate_tokens]
    overlap = len(present_significant)
    coverage = weighted_token_coverage(query, candidate)
    similarity = max((SequenceMatcher(None, normalized_query, value).ratio() for value in (title, artist_title, title_artist, album_artist, artist_album, candidate) if value), default=0.0)
    # SequenceMatcher can overvalue shared character runs such as "chains" and
    # "chainsaw". For multi-token queries with no complete significant token,
    # keep it secondary by discounting that character-only resemblance.
    if len(significant) > 1 and not present_significant:
        similarity *= 0.85
    confidence = max(coverage, similarity * 0.75)

    # Structured identifiers cannot rescue a different title/show.
    q_season, q_episode = extract_season_episode(query)
    c_season, c_episode = extract_season_episode(candidate)
    if q_season is not None and q_episode is not None and (q_season, q_episode) == (c_season, c_episode):
        show_tokens = {token for token in significant if not re.fullmatch(r"s?\d+e\d+|s\d+|e\d+", token)}
        if show_tokens and not (show_tokens & candidate_tokens):
            return MatchAssessment(confidence, "unrelated", True, overlap, coverage, similarity)

    count = len(significant) or len(query_tokens)
    connective_phrase = len(significant) >= 2 and any(token in LOW_INFORMATION for token in query_tokens)
    if connective_phrase and overlap < len(significant) and similarity < 0.55:
        return MatchAssessment(max(0.0, min(1.0, confidence)), "unrelated", True, overlap, coverage, similarity)
    unrelated = False
    code = "partial_tokens"
    if count <= 1:
        token = (significant or query_tokens or [""])[0]
        complete = token in candidate_tokens
        contains = len(token) >= 4 and len(candidate) >= 4 and (token in candidate or candidate in token)
        if complete or contains:
            code, confidence = "all_tokens", max(confidence, 0.8)
        elif similarity >= 0.34:
            code = "fuzzy"
        else:
            unrelated, code = True, "unrelated"
    elif count == 2:
        if overlap == 2:
            code, confidence = "all_tokens", max(confidence, 0.9)
        elif overlap == 1 and similarity >= 0.38:
            code = "partial_tokens"
        elif overlap == 0 and similarity >= 0.30:
            code = "fuzzy"
        else:
            unrelated, code = True, "unrelated"
    else:
        if overlap >= 2:
            code = "all_tokens" if overlap == len(significant) else "partial_tokens"
        elif coverage >= 0.45:
            code = "partial_tokens"
        elif similarity >= 0.42:
            code = "fuzzy"
        elif overlap == 0 and similarity < 0.32:
            unrelated, code = True, "unrelated"
        elif overlap == 1 and coverage < 0.24 and similarity < 0.34:
            unrelated, code = True, "unrelated"
    return MatchAssessment(max(0.0, min(1.0, confidence)), code, unrelated, overlap, coverage, similarity)


def match_confidence(query: Any, result: Mapping[str, Any] | Any) -> float:
    return assess_match(query, result).confidence


def is_clearly_unrelated(query: Any, result: Mapping[str, Any] | Any, *, return_reason: bool = False):
    assessment = assess_match(query, result)
    return (assessment.unrelated, assessment.code) if return_reason else assessment.unrelated


def match_explanation(query: Any, result: Mapping[str, Any] | Any) -> str:
    return assess_match(query, result).code

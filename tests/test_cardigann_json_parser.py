from pathlib import Path

from debripod.Services.indexers.cardigann.parser import parse_json


PAYLOAD = (Path(__file__).parent / "fixtures" / "cardigann" / "public_json_search.json").read_text(encoding="utf-8")


def test_json_dotted_rows_fields_has_not_and_filters():
    search = {"rows": {"selector": "data.items", "has": "hash", "fields": {
        "title": {"selector": "name"}, "infohash": {"selector": "hash"},
        "seeders": {"selector": "stats.seeders"}, "active": {"selector": "active"},
    }}}
    parsed = parse_json(PAYLOAD, search)
    assert len(parsed.releases) == 2
    assert parsed.releases[0]["seeders"] == 42


def test_json_empty_classification_is_explicit():
    changed = parse_json("{}", {"rows": {"selector": "items"}})
    empty = parse_json("{}", {"emptyIsNoResults": True, "rows": {"selector": "items"}})
    assert changed.error_classification == "layout_changed"
    assert empty.no_results and empty.error_classification == "no_results"


def test_json_multiple_child_rows_parent_selectors_and_result_templates():
    search = {"rows": {"selector": "data.movies", "attribute": "torrents", "multiple": True, "fields": {
        "quality": {"selector": "quality"},
        "title": {"selector": "..title"},
        "display": {"text": "{{ .Result.title }} {{ .Result.quality }}"},
        "infohash": {"selector": "hash"},
    }}}
    payload = {"data": {"movies": [{"title": "Matrix", "torrents": [{"quality": "1080p", "hash": "abc"}]}]}}
    parsed = parse_json(payload, search)
    assert parsed.releases == [{"quality": "1080p", "title": "Matrix", "display": "Matrix 1080p", "infohash": "abc"}]

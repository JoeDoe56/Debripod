from pathlib import Path

from debripod.Services.indexers.cardigann.parser import parse_html, parse_response


HTML = (Path(__file__).parent / "fixtures" / "cardigann" / "public_html_search.html").read_text(encoding="utf-8")


def test_html_rows_fields_attributes_and_filters():
    search = {"rows": {"selector": "tr.release", "fields": {
        "title": {"selector": ".title"},
        "details": {"selector": ".title", "attribute": "href", "prepend": "ignored"},
        "seeders": {"selector": ".seeders", "filters": [{"name": "regexp", "args": [r"(\d+)"]}]},
        "magnet": {"selector": ".magnet", "attribute": "href"},
        "optional": {"selector": ".missing", "optional": True, "default": ""},
    }}}
    parsed = parse_html(HTML, search, definition_id="fixture")
    assert parsed.error_classification == ""
    assert parsed.releases[0]["title"] == "Alice in Chains Dirt"
    assert parsed.releases[0]["seeders"] == "42"
    assert parsed.releases[0]["magnet"].startswith("magnet:")


def test_html_distinguishes_no_results_from_layout_change():
    assert parse_html('<div class="none">No results</div>', {"noResults": ".none", "rows": {"selector": ".row"}}).no_results
    changed = parse_html("<html></html>", {"rows": {"selector": ".row"}})
    assert changed.error_classification == "layout_changed" and not changed.no_results


def test_prowlarr_xml_raw_title_link_and_case_mapping():
    search = {
        "response": {"type": "xml"},
        "rows": {"selector": "rss > channel > item"},
        "fields": {
            "title": {"selector": "raw_title"},
            "download": {"selector": "link"},
            "category": {"selector": "raw_title", "case": {':contains("1080p")': 2, "*": 1}},
        },
    }
    xml = "<rss><channel><item><title>Example Show S01E01 1080p</title><link>magnet:?xt=urn:btih:abc</link></item></channel></rss>"
    parsed = parse_response(xml, "application/rss+xml", search, definition_id="rss")
    assert parsed.releases == [{"title": "Example Show S01E01 1080p", "download": "magnet:?xt=urn:btih:abc", "category": 2}]

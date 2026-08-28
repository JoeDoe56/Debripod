import logging

import pytest

from debripod.Services.indexers.cardigann.filters import DefinitionCompatibilityError, apply_filter, apply_filters


@pytest.mark.parametrize(("name", "value", "args", "expected"), [
    ("querystring", "https://x.test/?id=42", ["id"], "42"),
    ("regexp", "Seeders: 12", [r"(\d+)"], "12"),
    ("re_replace", "A  B", [r"\s+", "-"], "A-B"),
    ("split", "a|b", ["|", 1], "b"),
    ("replace", "abc", ["b", "B"], "aBc"),
    ("trim", " x ", [], "x"),
    ("prepend", "x", ["a"], "ax"),
    ("append", "x", ["z"], "xz"),
    ("tolower", "ABC", [], "abc"),
    ("toupper", "abc", [], "ABC"),
    ("urldecode", "a%20b", [], "a b"),
    ("urlencode", "a b", [], "a%20b"),
    ("htmldecode", "a&amp;b", [], "a&b"),
    ("htmlencode", "a&b", [], "a&amp;b"),
    ("validfilename", "a:b", [], "a_b"),
    ("diacritics", "Beyoncé", [], "Beyonce"),
    ("jsonjoinarray", '["a","b"]', ["|"], "a|b"),
])
def test_filters(name, value, args, expected):
    assert apply_filter(value, name, args) == expected


def test_validation_and_debug_filters():
    assert apply_filter("abc", "validate", ["^a"]) == "abc"
    assert apply_filter("abc", "andmatch", ["a", "c"]) == "abc"
    assert apply_filter("secret", "hexdump", logger=logging.getLogger("test")) == "secret"
    assert apply_filters(" A ", ["trim", "tolower"]) == "a"


def test_unknown_filter_names_definition_and_field():
    with pytest.raises(DefinitionCompatibilityError, match="demo.*title.*unknown"):
        apply_filter("x", "unknown", definition_id="demo", field="title")

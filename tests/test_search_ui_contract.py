from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_search_controls_have_one_source_row_after_clear():
    source = (REPO / "debripod" / "static" / "js" / "settings-ui.js").read_text(encoding="utf-8")
    unified = source[source.index("function libResultsToItems") : source.index("const q = state.libSearch.q")]
    assert unified.count('row_layout_key:"search-sources"') == 1
    assert "search-status-fixed" not in unified
    assert unified.index('label:"Search history"') < unified.index('label:"Enter filters"')
    assert unified.index('label:"Enter filters"') < unified.index('label:"Clear"')
    assert unified.index('label:"Clear"') < unified.index('row_layout_key:"search-sources"')


def test_search_history_does_not_render_the_redundant_engine_pill():
    source = (REPO / "debripod" / "static" / "js" / "settings-ui.js").read_text(encoding="utf-8")
    history = source[source.index("async function viewLibSearchHistory") : source.index("async function viewLibInfo")]
    assert "if(engine) pills.push(engine)" not in history
    assert "if(when) pills.push(String(when))" in history

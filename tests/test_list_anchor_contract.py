from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_new_pages_anchor_their_first_selection_to_the_originating_row():
    source = (REPO / "debripod" / "static" / "js" / "list-view.js").read_text(encoding="utf-8")
    assert "function selectedRowViewportY()" in source
    assert "view.entryAnchorY = entryAnchorY" in source
    assert "appendPageAnchorSpacer(itemsLayer)" in source
    assert "state.pageAnchorOffset = Math.max(0, Number(state.current.entryAnchorY) - paddingTop)" in source
    assert "!renderOptions.preserveEntryAnchor" in source


def test_library_root_drops_the_general_selected_row_top_clearance():
    css = (REPO / "debripod" / "static" / "debripod.css").read_text(encoding="utf-8")
    source = (REPO / "debripod" / "static" / "js" / "list-view.js").read_text(encoding="utf-8")
    assert ".ipodList.dpLibraryRoot" in css
    assert "padding-top:var(--screenFrame)" in css
    assert 'state.current.kind === "roots"' in source

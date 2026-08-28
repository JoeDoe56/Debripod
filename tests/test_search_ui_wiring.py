from pathlib import Path


def test_unified_search_model_owner_is_page_scoped_before_search_rendering():
    source = (Path(__file__).parents[1] / "debripod" / "static" / "js" / "settings-ui.js").read_text(encoding="utf-8")
    owner = source.index("let _libUnifiedSearchModel = null;")
    renderer = source.index("function libResultsToItems()")
    tasks = source.index("function libTasksRefreshList(preserveSel)")
    assert owner < renderer < tasks
    assert source.count("function libUnifiedSearchModel()") == 1

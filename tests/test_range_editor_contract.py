from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_range_editor_is_wheel_first_transactional_and_blur_safe():
    settings = (REPO / "debripod" / "static" / "js" / "settings-ui.js").read_text(encoding="utf-8")
    list_view = (REPO / "debripod" / "static" / "js" / "list-view.js").read_text(encoding="utf-8")
    assert "originalValue:current" in settings
    assert "if(view.rangeWheelArmed){\n      Promise.resolve(applyRangeEditor()).catch(()=>{});" in settings
    assert "function rangeEditorCenterHold()" in settings
    assert 'typeof config.onPreview === "function"' in settings
    assert "view.rangeValue = original" in settings
    assert "editor.committing || editor.cancelling" in list_view
    assert 'inp.addEventListener("blur"' in list_view
    assert "if(active === editor && !editor.committing && !editor.cancelling) cancelRangeEditor()" in list_view
    assert "if(!valid) return;" in list_view
    assert 'if(result && typeof result.catch === "function") result.catch(()=>{});' in list_view

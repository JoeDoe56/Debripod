from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_selection_input_is_rate_limited_and_coalesced():
    source = (REPO / "debripod" / "static" / "js" / "wheel-controls.js").read_text(encoding="utf-8")
    assert "const SELECTION_STEP_INTERVAL_MS = 1000 / 18" in source
    assert "let selectionStepPending = \"\"" in source
    assert "selectionStepPending = value" in source
    assert "window.cancelSelectionStepQueue = cancelSelectionStepQueue" in source
    assert "cancelSelectionStepQueue();" in source
    assert "queueSelectionStep(control)" in source

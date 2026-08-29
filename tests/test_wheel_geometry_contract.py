from pathlib import Path


CSS = (Path(__file__).resolve().parents[1] / "debripod" / "static" / "debripod.css").read_text(encoding="utf-8")


def test_classic_wheel_uses_one_responsive_size_and_ratio():
    assert "--wheelSize: clamp(220px, 61.5vw, 300px);" in CSS
    assert "--wheelCenterRatio: .368;" in CSS
    assert "--wheelCenterSize: calc(var(--wheelSize) * var(--wheelCenterRatio));" in CSS
    assert "width: var(--wheelCenterSize);" in CSS
    assert "height: var(--wheelCenterSize);" in CSS
    assert "width: 118px" not in CSS
    assert "height: 118px" not in CSS
    assert "width: 94px" not in CSS
    assert "height: 94px" not in CSS


def test_wheel_labels_and_icons_scale_from_wheel_size():
    assert "--wheelLabelEdgeInset: calc(var(--wheelSize) * .0525);" in CSS
    assert "calc(var(--wheelSize) * .054)" in CSS
    assert "width:calc(var(--wheelSize) * .085);" in CSS
    assert "height:calc(var(--wheelSize) * .048);" in CSS

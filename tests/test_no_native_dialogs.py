from pathlib import Path
import re


REPO = Path(__file__).resolve().parents[1]
NATIVE_DIALOG = re.compile(r"\b(?:prompt|alert|confirm)\s*\(")


def test_production_client_contains_no_native_dialogs():
    offenders = []
    for path in (REPO / "debripod" / "static").rglob("*.js"):
        if NATIVE_DIALOG.search(path.read_text(encoding="utf-8")):
            offenders.append(path.relative_to(REPO).as_posix())
    assert offenders == []

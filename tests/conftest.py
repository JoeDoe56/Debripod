from __future__ import annotations

import os
import tempfile
from pathlib import Path


# Test modules import runtime configuration during collection, so isolate the
# database before any of those imports can initialize persistent settings.
_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="debripod-pytest-"))
os.environ["DEBRIPOD_DATABASE"] = str(_TEST_DATA_DIR / "debripod.sqlite3")

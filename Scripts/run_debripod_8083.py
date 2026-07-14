from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "_debripod_cache"
LOG_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(ROOT))
sys.stdout = (LOG_DIR / "server-8083.out.log").open("a", encoding="utf-8", buffering=1)
sys.stderr = (LOG_DIR / "server-8083.err.log").open("a", encoding="utf-8", buffering=1)

from debripod import runtime  # noqa: E402


runtime.main()

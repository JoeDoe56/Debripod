from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from debripod.paths import cache_dir, migrate_legacy_runtime_caches
from debripod.storage.database import initialize_database


class RuntimeCacheTests(unittest.TestCase):
    def test_cache_is_owned_by_the_repository(self) -> None:
        configured_download = os.path.abspath(os.path.join(tempfile.gettempdir(), "media-downloads"))
        resolved = os.path.abspath(cache_dir())
        self.assertFalse(os.path.commonpath([configured_download, resolved]) == configured_download)
        self.assertTrue(resolved.endswith(os.path.join("data", "runtime_cache")))

    def test_failed_legacy_move_keeps_nonempty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "downloads"
            source = root / "_debripod_cache" / "search" / "cached.json"
            destination = Path(temp) / "central"
            source.parent.mkdir(parents=True)
            source.write_text("payload", encoding="utf-8")
            db_path = str(Path(temp) / "state.sqlite3")
            with patch.dict(os.environ, {"DEBRIPOD_DATABASE": db_path}), \
                 patch("debripod.paths.cache_dir", return_value=str(destination)), \
                 patch("debripod.paths.shutil.move", side_effect=OSError("blocked")):
                initialize_database()
                result = migrate_legacy_runtime_caches([str(root)])
            self.assertEqual(result["failed"], 1)
            self.assertTrue(source.exists())
            self.assertTrue(source.parent.exists())
            self.assertTrue(source.parent.parent.exists())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from debripod.storage.database import initialize_database
from debripod.storage.media_likes import (
    build_media_key,
    get_media_like,
    list_media_likes,
    set_media_like,
)


class MediaLikeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tempdir.name, "likes.sqlite3")
        self.env = patch.dict(os.environ, {"DEBRIPOD_DATABASE": self.db_path})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.tempdir.cleanup()

    def test_all_local_media_types_round_trip(self) -> None:
        for media_type in ("music", "movie", "episode", "video", "youtube"):
            target = {
                "media_type": media_type,
                "root_id": "root",
                "rel": f"{media_type}/item.ext",
                "source": "library",
                "title": media_type.title(),
            }
            with self.subTest(media_type=media_type):
                key = build_media_key(target)
                saved = set_media_like("alice", target, True)
                self.assertEqual(saved["media_key"], key)
                self.assertTrue(get_media_like("alice", key)["liked"])

    def test_likes_are_user_scoped(self) -> None:
        target = {
            "media_type": "movie",
            "root_id": "movies",
            "rel": "Example (2026).mkv",
            "source": "library",
        }
        key = build_media_key(target)
        set_media_like("alice", target, True)
        self.assertTrue(get_media_like("alice", key)["liked"])
        self.assertIsNone(get_media_like("bob", key))
        set_media_like("bob", target, False)
        self.assertTrue(get_media_like("alice", key)["liked"])
        self.assertFalse(get_media_like("bob", key)["liked"])

    def test_list_filters_type_and_root(self) -> None:
        set_media_like(
            "alice",
            {"media_type": "video", "root_id": "a", "rel": "one.mp4", "source": "library"},
            True,
        )
        set_media_like(
            "alice",
            {"media_type": "video", "root_id": "b", "rel": "two.mp4", "source": "library"},
            True,
        )
        self.assertEqual(len(list_media_likes("alice", media_type="video")), 2)
        self.assertEqual(len(list_media_likes("alice", media_type="video", root_id="a")), 1)


if __name__ == "__main__":
    unittest.main()

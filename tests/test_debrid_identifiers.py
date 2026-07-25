from __future__ import annotations

import unittest

from debripod.Services.debrid.identifiers import (
    first_identifier,
    identifiers_equal,
    normalize_identifier,
    normalize_identifier_list,
)


class DebridIdentifierTests(unittest.TestCase):
    def test_zero_is_preserved(self) -> None:
        self.assertEqual(normalize_identifier(0), "0")
        self.assertEqual(normalize_identifier("0"), "0")

    def test_missing_and_composite_values_are_rejected(self) -> None:
        for value in (None, "", "   ", [], {}):
            with self.subTest(value=value):
                self.assertIsNone(normalize_identifier(value))

    def test_first_present_identifier_does_not_skip_zero(self) -> None:
        payload = {"id": 0, "file_id": 42}
        self.assertEqual(first_identifier(payload, "id", "file_id"), "0")

    def test_identifier_list_preserves_zero_and_deduplicates(self) -> None:
        self.assertEqual(
            normalize_identifier_list([0, "0", "", None, " 7 ", 7]),
            ["0", "7"],
        )

    def test_comparison_uses_normalized_values(self) -> None:
        self.assertTrue(identifiers_equal(0, "0"))
        self.assertTrue(identifiers_equal(" 7 ", 7))
        self.assertFalse(identifiers_equal("", 0))


if __name__ == "__main__":
    unittest.main()

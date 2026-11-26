"""PROBE - DO NOT MERGE. Synthetic tests for the Codex auto-review integration test."""
import unittest

from probe.clamp import clamp


class ClampTests(unittest.TestCase):
    def test_inside_range(self):
        self.assertEqual(clamp(5, 0, 10), 5)

    def test_below_and_above(self):
        self.assertEqual(clamp(-1, 0, 10), 0)
        self.assertEqual(clamp(11, 0, 10), 10)


if __name__ == "__main__":
    unittest.main()

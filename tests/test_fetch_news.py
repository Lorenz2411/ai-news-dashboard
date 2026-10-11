import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_news as fn  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


class ParseTests(unittest.TestCase):
    def test_rss(self):
        items = fn.parse_feed((FIX / "rss.xml").read_bytes(), "Press", "press")
        self.assertEqual(len(items), 1)  # item without a link is skipped
        it = items[0]
        self.assertEqual(it["link"], "https://example.com/agents-funding")
        self.assertEqual(it["summary"], "The company’s new funding round values it at $1B.")
        self.assertEqual(it["published"], "2026-10-09T14:30:00+00:00")
        self.assertIn("Business", it["topics"])
        self.assertIn("Tools", it["topics"])

    def test_atom_prefers_alternate_link(self):
        it = fn.parse_feed((FIX / "atom.xml").read_bytes(), "Lab", "lab")[0]
        self.assertEqual(it["link"], "https://example.org/benchmark")
        self.assertEqual(it["published"], "2026-10-10T08:00:00+00:00")
        self.assertEqual(set(it["topics"]) & {"Models", "Research"}, {"Models", "Research"})

    def test_clean_truncates_on_word_boundary(self):
        out = fn.clean("word " * 100, limit=20)
        self.assertTrue(out.endswith("…"))
        self.assertLessEqual(len(out), 21)


class MergeTests(unittest.TestCase):
    def test_keeps_first_seen_and_drops_stale(self):
        now = datetime(2026, 10, 11, tzinfo=timezone.utc)
        old = [
            {"id": "a", "published": (now - timedelta(days=1)).isoformat(), "first_seen": "2026-10-10T00:00:00+00:00"},
            {"id": "stale", "published": (now - timedelta(days=60)).isoformat(), "first_seen": "x"},
        ]
        new = [
            {"id": "a", "published": (now - timedelta(days=1)).isoformat(), "title": "updated"},
            {"id": "b", "published": now.isoformat()},
        ]
        out = fn.merge(old, new, now, max_age_days=30)
        self.assertEqual([i["id"] for i in out], ["b", "a"])
        self.assertEqual(out[1]["first_seen"], "2026-10-10T00:00:00+00:00")
        self.assertEqual(out[1]["title"], "updated")


if __name__ == "__main__":
    unittest.main()

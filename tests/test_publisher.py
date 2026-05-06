from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from wazzup.publisher import enforce_retention, write_json, write_manifest


class PublisherTests(unittest.TestCase):
    def test_retention_uses_data_path_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            old_article = data_dir / "articles" / "2026" / "03" / "01.json"
            current_article = data_dir / "articles" / "2026" / "05" / "06.json"
            old_briefing = data_dir / "briefings" / "2026" / "03" / "01" / "hourly-10.json"
            current_briefing = data_dir / "briefings" / "2026" / "05" / "06" / "hourly-10.json"
            for path in [old_article, current_article, old_briefing, current_briefing]:
                write_json(path, {"ok": True})

            enforce_retention(data_dir, datetime(2026, 5, 6, tzinfo=UTC), 35)
            write_manifest(data_dir, datetime(2026, 5, 6, tzinfo=UTC), 35)

            self.assertFalse(old_article.exists())
            self.assertFalse(old_briefing.exists())
            self.assertTrue(current_article.exists())
            self.assertTrue(current_briefing.exists())
            manifest = (data_dir / "manifest.json").read_text(encoding="utf-8")
            self.assertIn("articles/2026/05/06.json", manifest)
            self.assertIn("briefings/2026/05/06/hourly-10.json", manifest)
            self.assertNotIn("2026/03", manifest)


if __name__ == "__main__":
    unittest.main()

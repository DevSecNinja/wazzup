from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from wazzup.publisher import enforce_retention, write_data, write_manifest


class PublisherTests(unittest.TestCase):
    def test_retention_uses_data_path_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            old_article = data_dir / "articles" / "2026" / "03" / "01.yaml"
            current_article = data_dir / "articles" / "2026" / "05" / "06.yaml"
            old_briefing = data_dir / "briefings" / "2026" / "03" / "01" / "hourly-10.yaml"
            current_briefing = data_dir / "briefings" / "2026" / "05" / "06" / "hourly-10.yaml"
            for path in [old_article, current_article, old_briefing, current_briefing]:
                write_data(path, {"ok": True})

            enforce_retention(data_dir, datetime(2026, 5, 6, tzinfo=UTC), 35)
            write_manifest(data_dir, datetime(2026, 5, 6, tzinfo=UTC), 35)

            self.assertFalse(old_article.exists())
            self.assertFalse(old_article.with_suffix(".json").exists())
            self.assertFalse(old_briefing.exists())
            self.assertFalse(old_briefing.with_suffix(".json").exists())
            self.assertTrue(current_article.exists())
            self.assertTrue(current_article.with_suffix(".json").exists())
            self.assertTrue(current_briefing.exists())
            self.assertTrue(current_briefing.with_suffix(".json").exists())
            manifest = (data_dir / "manifest.yaml").read_text(encoding="utf-8")
            self.assertIn("articles/2026/05/06.yaml", manifest)
            self.assertIn("briefings/2026/05/06/hourly-10.yaml", manifest)
            self.assertNotIn("2026/03", manifest)


if __name__ == "__main__":
    unittest.main()

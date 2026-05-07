from __future__ import annotations

import os
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from wazzup.pipeline import generate
from wazzup.validate_data import validate_data_dir


class PipelineTests(unittest.TestCase):
    def test_generate_static_data_from_fixtures(self) -> None:
        previous_provider = os.environ.get("AI_PROVIDER")
        os.environ["AI_PROVIDER"] = "fake"
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                public_dir = Path(tmp_dir)
                # Copy static PWA shell because pipeline writes only data files.
                fixed_now = datetime(2026, 5, 6, 18, 0, tzinfo=UTC)
                with patch("wazzup.pipeline.utc_now", return_value=fixed_now):
                    latest = generate(
                        [
                            "--fixture-dir",
                            "tests/fixtures",
                            "--public-dir",
                            str(public_dir),
                            "--force-briefing",
                            "hourly",
                        ]
                    )
                self.assertIn("latestBriefingUrl", latest)
                validate_data_dir(public_dir / "data")
                briefing = (public_dir / "data" / latest["latestBriefingUrl"]).read_text(encoding="utf-8")
                self.assertIn("Top updates", briefing)
                briefing_json = json.loads((public_dir / "data" / latest["latestBriefingUrl"]).read_text(encoding="utf-8"))
                self.assertEqual("2026-05-05T22:00:00Z", briefing_json["windowStart"])
                self.assertEqual("2026-05-06T18:00:00Z", briefing_json["windowEnd"])
                self.assertIn("publishedAt", briefing_json["citations"][0])
                self.assertIn("temperature", briefing_json["citations"][0])
                self.assertIn(briefing_json["citations"][0]["temperature"]["level"], {"hot", "warm", "cool"})
                self.assertIn("title", briefing_json["sections"][0]["bullets"][0])
                self.assertIn("description", briefing_json["sections"][0]["bullets"][0])
                status_json = json.loads((public_dir / "data" / "sources" / "status.json").read_text(encoding="utf-8"))
                self.assertTrue(all("lastArticleAt" in source for source in status_json["sources"]))
        finally:
            if previous_provider is None:
                os.environ.pop("AI_PROVIDER", None)
            else:
                os.environ["AI_PROVIDER"] = previous_provider


if __name__ == "__main__":
    unittest.main()

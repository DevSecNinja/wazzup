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
    def test_generate_auto_selects_due_morning_briefing(self) -> None:
        previous_provider = os.environ.get("AI_PROVIDER")
        os.environ["AI_PROVIDER"] = "fake"
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                public_dir = Path(tmp_dir)
                fixed_now = datetime(2026, 5, 6, 5, 10, tzinfo=UTC)
                with patch("wazzup.pipeline.utc_now", return_value=fixed_now):
                    latest = generate(
                        [
                            "--fixture-dir",
                            "tests/fixtures",
                            "--public-dir",
                            str(public_dir),
                            "--force-briefing",
                            "auto",
                        ]
                    )
                self.assertTrue(latest["latestBriefingUrl"].endswith("/morning.json"))
                briefing = json.loads((public_dir / latest["latestBriefingUrl"]).read_text(encoding="utf-8"))
                self.assertEqual("morning", briefing["kind"])
        finally:
            if previous_provider is None:
                os.environ.pop("AI_PROVIDER", None)
            else:
                os.environ["AI_PROVIDER"] = previous_provider

    def test_generate_auto_skips_existing_due_morning_briefing(self) -> None:
        previous_provider = os.environ.get("AI_PROVIDER")
        os.environ["AI_PROVIDER"] = "fake"
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                public_dir = Path(tmp_dir)
                fixed_now = datetime(2026, 5, 6, 5, 10, tzinfo=UTC)
                with patch("wazzup.pipeline.utc_now", return_value=fixed_now):
                    generate(
                        [
                            "--fixture-dir",
                            "tests/fixtures",
                            "--public-dir",
                            str(public_dir),
                            "--force-briefing",
                            "morning",
                        ]
                    )
                with patch("wazzup.pipeline.utc_now", return_value=fixed_now):
                    latest = generate(
                        [
                            "--fixture-dir",
                            "tests/fixtures",
                            "--public-dir",
                            str(public_dir),
                            "--force-briefing",
                            "auto",
                        ]
                    )
                briefing = json.loads((public_dir / latest["latestBriefingUrl"]).read_text(encoding="utf-8"))
                self.assertEqual("hourly", briefing["kind"])
                self.assertTrue((latest.get("latestMorningBriefingUrl") or "").endswith("/morning.json"))
        finally:
            if previous_provider is None:
                os.environ.pop("AI_PROVIDER", None)
            else:
                os.environ["AI_PROVIDER"] = previous_provider

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
                self.assertIn("latestArticlesUrl", latest)
                self.assertTrue(latest["latestBriefingUrl"].startswith("data/"))
                self.assertTrue(latest["latestArticlesUrl"].startswith("data/"))
                validate_data_dir(public_dir / "data")
                briefing_path = public_dir / latest["latestBriefingUrl"]
                articles_path = public_dir / latest["latestArticlesUrl"]
                briefing = briefing_path.read_text(encoding="utf-8")
                self.assertIn("Top updates", briefing)
                briefing_json = json.loads(briefing_path.read_text(encoding="utf-8"))
                articles_text = articles_path.read_text(encoding="utf-8")
                articles_json = json.loads(articles_text)
                self.assertEqual("2026-05-05T22:00:00Z", briefing_json["windowStart"])
                self.assertEqual("2026-05-06T18:00:00Z", briefing_json["windowEnd"])
                self.assertIsInstance(articles_json["items"], list)
                self.assertTrue(articles_text.lstrip().startswith("{"))
                self.assertIn("publishedAt", briefing_json["citations"][0])
                self.assertIn("sourceTag", briefing_json["citations"][0])
                self.assertIn("tags", briefing_json["citations"][0])
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

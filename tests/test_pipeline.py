from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

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
        finally:
            if previous_provider is None:
                os.environ.pop("AI_PROVIDER", None)
            else:
                os.environ["AI_PROVIDER"] = previous_provider


if __name__ == "__main__":
    unittest.main()

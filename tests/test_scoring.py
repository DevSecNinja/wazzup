from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path

from wazzup.config import load_app_config, load_sources
from wazzup.feeds import parse_feed
from wazzup.scoring import score_items


class ScoringTests(unittest.TestCase):
    def test_threat_intelligence_source_scores_high(self) -> None:
        sources = load_sources("config/sources.yml")
        app_config = load_app_config("config/interests.yml")
        items = []
        for source in sources:
            path = Path("tests/fixtures") / f"{source.id}.xml"
            if not path.exists():
                continue
            items.extend(parse_feed(source, path.read_bytes()))
        scored = score_items(items, sources, app_config, datetime(2026, 5, 6, 17, tzinfo=UTC))
        self.assertEqual("microsoft-security-threat-intelligence", scored[0].item.source_id)
        self.assertIn("security", scored[0].matched_interests)


if __name__ == "__main__":
    unittest.main()

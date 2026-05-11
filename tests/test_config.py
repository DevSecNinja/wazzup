from __future__ import annotations

import unittest

from wazzup.config import load_app_config, load_sources

MIN_EXPECTED_SOURCES = 15


class ConfigTests(unittest.TestCase):
    def test_load_sources(self) -> None:
        sources = load_sources("config/sources.yml")
        self.assertGreaterEqual(len(sources), MIN_EXPECTED_SOURCES)
        self.assertEqual("microsoft-security-threat-intelligence", sources[1].id)
        self.assertEqual("MS TI", sources[1].source_tag)
        self.assertIn("economist", {source.id for source in sources})
        self.assertIn("financial-times", {source.id for source in sources})
        self.assertIn("the-hacker-news", {source.id for source in sources})
        self.assertNotIn("zandvoortsecourant", {source.id for source in sources})
        self.assertIn("tech", {category for source in sources for category in source.categories})
        self.assertIn("Accept", sources[0].headers)

    def test_load_app_config(self) -> None:
        config = load_app_config("config/interests.yml")
        self.assertEqual("en", config.summary_language)
        self.assertEqual(35, config.retention_days)
        self.assertGreaterEqual(len(config.interests), 3)
        negative_interests = {interest.id: interest for interest in config.interests if interest.weight < 0}
        self.assertIn("uk-politics", negative_interests)
        self.assertIn("celebrity-entertainment", negative_interests)
        self.assertIn("glamour", negative_interests["celebrity-entertainment"].keywords)


if __name__ == "__main__":
    unittest.main()

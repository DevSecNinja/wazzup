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
        self.assertIn("formula1-official-news", {source.id for source in sources})
        self.assertIn("autosport-f1", {source.id for source in sources})
        self.assertIn("motorsport-f1", {source.id for source in sources})
        self.assertIn("racefans", {source.id for source in sources})
        self.assertIn("nba-official-news", {source.id for source in sources})
        self.assertIn("espn-nba", {source.id for source in sources})
        self.assertIn("github-blog", {source.id for source in sources})
        self.assertIn("azure-updates", {source.id for source in sources})
        self.assertIn("tech", {category for source in sources for category in source.categories})
        self.assertIn("formula-1", {category for source in sources for category in source.categories})
        self.assertIn("nba", {category for source in sources for category in source.categories})
        timeout_by_id = {source.id: source.timeout_seconds for source in sources}
        enabled_by_id = {source.id: source.enabled for source in sources}
        self.assertEqual(30, timeout_by_id["microsoft-security-blog"])
        self.assertEqual(8, timeout_by_id["nba-official-news"])
        self.assertFalse(enabled_by_id["nba-official-news"])
        self.assertTrue(enabled_by_id["espn-nba"])
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
        interests = {interest.id: interest for interest in config.interests}
        self.assertIn("formula-1", interests)
        self.assertIn("nba", interests)
        self.assertIn("grand prix", interests["formula-1"].keywords)
        self.assertIn("basketball", interests["nba"].keywords)


if __name__ == "__main__":
    unittest.main()

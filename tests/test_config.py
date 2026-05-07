from __future__ import annotations

import unittest

from wazzup.config import load_app_config, load_sources


class ConfigTests(unittest.TestCase):
    def test_load_sources(self) -> None:
        sources = load_sources("config/sources.yml")
        self.assertEqual(19, len(sources))
        self.assertEqual("microsoft-security-threat-intelligence", sources[1].id)
        self.assertEqual("MS TI", sources[1].source_tag)
        self.assertIn("economist", {source.id for source in sources})
        self.assertIn("financial-times", {source.id for source in sources})
        self.assertIn("the-hacker-news", {source.id for source in sources})
        self.assertIn("tech", {category for source in sources for category in source.categories})
        self.assertIn("Accept", sources[0].headers)

    def test_load_app_config(self) -> None:
        config = load_app_config("config/interests.yml")
        self.assertEqual("en", config.summary_language)
        self.assertEqual(35, config.retention_days)
        self.assertGreaterEqual(len(config.interests), 3)


if __name__ == "__main__":
    unittest.main()

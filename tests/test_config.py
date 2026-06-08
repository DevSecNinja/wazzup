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
        self.assertIn("fd-nl", {source.id for source in sources})
        self.assertIn("the-hacker-news", {source.id for source in sources})
        self.assertIn("formula1-official-news", {source.id for source in sources})
        self.assertIn("autosport-f1", {source.id for source in sources})
        self.assertIn("motorsport-f1", {source.id for source in sources})
        self.assertIn("racefans", {source.id for source in sources})
        self.assertIn("nba-official-news", {source.id for source in sources})
        self.assertIn("espn-nba", {source.id for source in sources})
        self.assertIn("mick-beer", {source.id for source in sources})
        self.assertIn("github-blog", {source.id for source in sources})
        self.assertIn("openai-news", {source.id for source in sources})
        self.assertIn("omar-knows-ai", {source.id for source in sources})
        self.assertIn("anthropic-news", {source.id for source in sources})
        self.assertIn("hugging-face-blog", {source.id for source in sources})
        self.assertIn("azure-updates", {source.id for source in sources})
        self.assertIn("tech", {category for source in sources for category in source.categories})
        self.assertIn("privacy", {category for source in sources for category in source.categories})
        self.assertIn("ai", {category for source in sources for category in source.categories})
        self.assertIn("formula-1", {category for source in sources for category in source.categories})
        self.assertIn("nba", {category for source in sources for category in source.categories})
        timeout_by_id = {source.id: source.timeout_seconds for source in sources}
        enabled_by_id = {source.id: source.enabled for source in sources}
        feed_url_by_id = {source.id: source.feed_url for source in sources}
        weight_by_id = {source.id: source.weight for source in sources}
        self.assertEqual(30, timeout_by_id["microsoft-security-blog"])
        self.assertEqual("https://www.omarknows.ai/feed", feed_url_by_id["omar-knows-ai"])
        self.assertGreaterEqual(weight_by_id["omar-knows-ai"], 1.2)
        self.assertEqual("https://mickbeer.com/feed/", feed_url_by_id["mick-beer"])
        self.assertGreaterEqual(weight_by_id["mick-beer"], 1.2)
        self.assertEqual("https://fd.nl/?rss", feed_url_by_id["fd-nl"])
        self.assertEqual(8, timeout_by_id["nba-official-news"])
        self.assertFalse(enabled_by_id["nba-official-news"])
        self.assertTrue(enabled_by_id["espn-nba"])
        self.assertIn("Accept", sources[0].headers)

    def test_load_app_config(self) -> None:
        config = load_app_config("config/interests.yml")
        self.assertEqual("en", config.summary_language)
        self.assertEqual(3, config.retention_days)
        self.assertGreaterEqual(len(config.interests), 3)
        negative_interests = {interest.id: interest for interest in config.interests if interest.weight < 0}
        self.assertIn("uk-politics", negative_interests)
        self.assertIn("celebrity-entertainment", negative_interests)
        self.assertIn("glamour", negative_interests["celebrity-entertainment"].keywords)
        interests = {interest.id: interest for interest in config.interests}
        self.assertIn("privacy", interests)
        self.assertIn("formula-1", interests)
        self.assertIn("nba", interests)
        self.assertIn("finance-investing", interests)
        self.assertIn("data protection", interests["privacy"].keywords)
        self.assertGreater(interests["privacy"].weight, 1.0)
        self.assertIn("grand prix", interests["formula-1"].keywords)
        self.assertIn("investing", interests["finance-investing"].keywords)
        self.assertGreater(interests["finance-investing"].weight, interests["nba"].weight)
        self.assertEqual(0.7, interests["nba"].weight)
        self.assertIn("basketball", interests["nba"].keywords)


if __name__ == "__main__":
    unittest.main()

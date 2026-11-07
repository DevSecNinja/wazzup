from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from wazzup.config import load_sources
from wazzup.feeds import canonicalize_url, cluster_related_stories, deduplicate, parse_feed


class FeedTests(unittest.TestCase):
    def test_canonicalize_url_removes_tracking(self) -> None:
        url = canonicalize_url("https://Example.com/path/?utm_source=x&keep=y#fragment")
        self.assertEqual("https://example.com/path/?keep=y", url)

    def test_parse_rss_fixture(self) -> None:
        source = load_sources("config/sources.yml")[0]
        payload = Path("tests/fixtures/microsoft-security-blog.xml").read_bytes()
        items = parse_feed(source, payload)
        self.assertEqual(1, len(items))
        self.assertEqual("Microsoft Defender improves AI security operations", items[0].title)
        self.assertEqual("https://www.microsoft.com/en-us/security/blog/example-ai-soc/", items[0].canonical_url)
        self.assertEqual("MS Security", items[0].source_tag)
        self.assertIn("MS Security", items[0].tags)
        self.assertIn("security", items[0].tags)
        self.assertEqual(len(items[0].tags), len(set(tag.lower() for tag in items[0].tags)))

    def test_parse_feed_skips_items_without_valid_publication_date(self) -> None:
        source = load_sources("config/sources.yml")[0]
        payload = b"""<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>Dated article</title>
    <link>https://example.com/dated</link>
    <pubDate>Wed, 06 May 2026 15:00:00 +0000</pubDate>
    <description>Valid publication date.</description>
  </item>
  <item>
    <title>Undated article</title>
    <link>https://example.com/undated</link>
    <description>Missing publication date.</description>
  </item>
  <item>
    <title>Invalid date article</title>
    <link>https://example.com/invalid</link>
    <pubDate>not a date</pubDate>
    <description>Invalid publication date.</description>
  </item>
</channel></rss>"""

        items = parse_feed(source, payload, datetime(2026, 5, 10, 10, tzinfo=UTC))

        self.assertEqual(["Dated article"], [item.title for item in items])
        self.assertEqual("2026-05-06T15:00:00Z", items[0].published_at)

    def test_deduplicate_prefers_priority_source_for_same_title_day(self) -> None:
        sources = load_sources("config/sources.yml")
        general = parse_feed(sources[0], Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        priority = parse_feed(sources[1], Path("tests/fixtures/microsoft-security-threat-intelligence.xml").read_bytes())[0]
        duplicate_priority = replace(
            priority,
            canonical_url="https://example.com/syndicated-copy",
            published_at=general.published_at,
            raw_ref="syndicated-copy",
            title=general.title,
        )
        deduped = deduplicate([general, duplicate_priority])
        self.assertEqual(1, len(deduped))
        self.assertEqual("microsoft-security-threat-intelligence", deduped[0].source_id)
        self.assertEqual([general.id], [item.id for item in deduped[0].related_items])

    def test_deduplicate_preserves_related_sources_for_same_story(self) -> None:
        sources = load_sources("config/sources.yml")
        primary = parse_feed(sources[0], Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        related = replace(
            primary,
            id="item-related-source",
            source_id="related-source",
            source_name="Related Source",
            source_tag="Related",
            url="https://related.example/story",
            canonical_url="https://related.example/story",
            raw_ref="related-story",
        )

        deduped = deduplicate([primary, related])

        self.assertEqual(1, len(deduped))
        self.assertEqual(primary.id, deduped[0].id)
        self.assertEqual(["item-related-source"], [item.id for item in deduped[0].related_items])
        self.assertEqual("related-source", deduped[0].related_items[0].source_id)

    def test_deduplicate_groups_fixture_duplicates(self) -> None:
        source = load_sources("config/sources.yml")[0]
        fixture_items = parse_feed(source, Path("tests/fixtures/story-clustering.xml").read_bytes())
        duplicate = replace(
            fixture_items[0],
            id="item-duplicate-source",
            source_id="duplicate-source",
            source_name="Duplicate Source",
            source_tag="Duplicate",
            canonical_url="https://duplicate.example/acme-vpn-cve-2026-4242",
            url="https://duplicate.example/acme-vpn-cve-2026-4242",
            raw_ref="duplicate-entry",
        )

        deduped = deduplicate([fixture_items[0], duplicate])

        self.assertEqual(1, len(deduped))
        self.assertEqual(["item-duplicate-source"], [item.id for item in deduped[0].related_items])

    def test_cluster_related_stories_groups_near_duplicates(self) -> None:
        source = load_sources("config/sources.yml")[0]
        fixture_items = parse_feed(source, Path("tests/fixtures/story-clustering.xml").read_bytes())
        first_story = fixture_items[0]
        near_duplicate = replace(
            fixture_items[1],
            id="item-near-duplicate-source",
            source_id="near-duplicate-source",
            source_name="Near Duplicate Source",
            source_tag="Near Duplicate",
        )

        clustered = cluster_related_stories([first_story, near_duplicate])

        self.assertEqual(1, len(clustered))
        self.assertEqual(["item-near-duplicate-source"], [item.id for item in clustered[0].related_items])

    def test_cluster_related_stories_keeps_same_topic_different_story_separate(self) -> None:
        source = load_sources("config/sources.yml")[0]
        fixture_items = parse_feed(source, Path("tests/fixtures/story-clustering.xml").read_bytes())
        first_story = fixture_items[0]
        different_story = replace(
            fixture_items[2],
            id="item-different-story-source",
            source_id="different-story-source",
            source_name="Different Story Source",
            source_tag="Different Story",
        )

        clustered = cluster_related_stories([first_story, different_story])

        self.assertEqual(2, len(clustered))
        self.assertTrue(all(not item.related_items for item in clustered))


if __name__ == "__main__":
    unittest.main()

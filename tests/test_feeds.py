from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from wazzup.config import load_sources
from wazzup.feeds import canonicalize_url, deduplicate, parse_feed


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


if __name__ == "__main__":
    unittest.main()

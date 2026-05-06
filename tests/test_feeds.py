from __future__ import annotations

import unittest
from dataclasses import replace
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


if __name__ == "__main__":
    unittest.main()

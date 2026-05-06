from __future__ import annotations

import unittest
from pathlib import Path

from wazzup.config import load_sources
from wazzup.feeds import canonicalize_url, parse_feed


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


if __name__ == "__main__":
    unittest.main()

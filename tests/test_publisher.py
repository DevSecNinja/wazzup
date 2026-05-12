from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from wazzup.ai import SummaryResponse, TransparencyReportResponse
from wazzup.models import AppConfig, ContentItem, ScoredItem
from wazzup.publisher import build_briefing, enforce_retention, write_data, write_manifest


class PublisherTests(unittest.TestCase):
    def test_retention_uses_data_path_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            old_article = data_dir / "articles" / "2026" / "03" / "01.yaml"
            current_article = data_dir / "articles" / "2026" / "05" / "06.yaml"
            old_briefing = data_dir / "briefings" / "2026" / "03" / "01" / "hourly-10.yaml"
            current_briefing = data_dir / "briefings" / "2026" / "05" / "06" / "hourly-10.yaml"
            old_report = data_dir / "transparency" / "2026" / "03" / "01" / "hourly-10.yaml"
            current_report = data_dir / "transparency" / "2026" / "05" / "06" / "hourly-10.yaml"
            for path in [old_article, current_article, old_briefing, current_briefing, old_report, current_report]:
                write_data(path, {"ok": True})
            old_report.with_suffix(".md").write_text("# Old report\n", encoding="utf-8")
            current_report.with_suffix(".md").write_text("# Current report\n", encoding="utf-8")

            enforce_retention(data_dir, datetime(2026, 5, 6, tzinfo=UTC), 35)
            write_manifest(data_dir, datetime(2026, 5, 6, tzinfo=UTC), 35)

            self.assertFalse(old_article.exists())
            self.assertFalse(old_article.with_suffix(".json").exists())
            self.assertFalse(old_briefing.exists())
            self.assertFalse(old_briefing.with_suffix(".json").exists())
            self.assertFalse(old_report.exists())
            self.assertFalse(old_report.with_suffix(".json").exists())
            self.assertFalse(old_report.with_suffix(".md").exists())
            self.assertTrue(current_article.exists())
            self.assertTrue(current_article.with_suffix(".json").exists())
            self.assertTrue(current_briefing.exists())
            self.assertTrue(current_briefing.with_suffix(".json").exists())
            self.assertTrue(current_report.exists())
            self.assertTrue(current_report.with_suffix(".json").exists())
            self.assertTrue(current_report.with_suffix(".md").exists())
            manifest = (data_dir / "manifest.yaml").read_text(encoding="utf-8")
            self.assertIn("articles/2026/05/06.yaml", manifest)
            self.assertIn("briefings/2026/05/06/hourly-10.yaml", manifest)
            self.assertIn("transparency/2026/05/06/hourly-10.yaml", manifest)
            self.assertNotIn("2026/03", manifest)

    def test_markdown_transparency_report_contains_metrics(self) -> None:
        from wazzup.publisher import build_transparency_report, markdown_transparency_report

        item = ContentItem(
            schema_version=1,
            id="item-primary",
            source_id="primary-source",
            source_name="Primary Source",
            source_tag="Primary",
            source_type="rss",
            title="Shared story",
            url="https://example.com/primary",
            canonical_url="https://example.com/story",
            published_at="2026-05-06T09:00:00Z",
            discovered_at="2026-05-06T09:00:00Z",
            authors=[],
            tags=["tech"],
            language="en",
            summary="Primary summary",
            content_hash="primary",
            raw_ref="primary",
        )
        scored = ScoredItem(item, 30, [], [], "dup-story", "fresh")
        payload = build_transparency_report(
            "hourly",
            datetime(2026, 5, 6, 8, tzinfo=UTC),
            datetime(2026, 5, 6, 9, tzinfo=UTC),
            datetime(2026, 5, 6, 9, tzinfo=UTC),
            AppConfig("en", 35, "Europe/Amsterdam", "07:00", "20:00", []),
            [scored],
            [],
            TransparencyReportResponse(
                title="Transparency report for hourly briefing",
                summary="A short summary.",
                sections=[{"title": "Selection", "bullets": ["Selected item-primary."]}],
                provider={"type": "fake", "promptVersion": "transparency-v1"},
            ),
        )

        markdown = markdown_transparency_report(payload)

        self.assertIn("# Transparency report for hourly briefing", markdown)
        self.assertIn("- Selected items: 1", markdown)
        self.assertIn("- Selected item-primary.", markdown)

    def test_build_briefing_includes_related_source_citations(self) -> None:
        item = ContentItem(
            schema_version=1,
            id="item-primary",
            source_id="primary-source",
            source_name="Primary Source",
            source_tag="Primary",
            source_type="rss",
            title="Shared story",
            url="https://example.com/primary",
            canonical_url="https://example.com/story",
            published_at="2026-05-06T09:00:00Z",
            discovered_at="2026-05-06T09:00:00Z",
            authors=[],
            tags=["tech"],
            language="en",
            summary="Primary summary",
            content_hash="primary",
            raw_ref="primary",
        )
        related = replace(
            item,
            id="item-related",
            source_id="related-source",
            source_name="Related Source",
            source_tag="Related",
            url="https://example.com/related",
            raw_ref="related",
        )
        scored = ScoredItem(
            item=replace(item, related_items=(related,)),
            score=30,
            score_reasons=[],
            matched_interests=[],
            duplicate_group_id="dup-story",
            freshness_bucket="fresh",
        )
        briefing = build_briefing(
            "hourly",
            datetime(2026, 5, 6, 8, tzinfo=UTC),
            datetime(2026, 5, 6, 9, tzinfo=UTC),
            datetime(2026, 5, 6, 9, tzinfo=UTC),
            AppConfig("en", 35, "Europe/Amsterdam", "07:00", "20:00", []),
            [scored],
            SummaryResponse(
                headline="Shared story",
                sections=[{"title": "Top updates", "bullets": [{"title": "Shared story", "text": "Text", "citations": ["item-primary", "item-related"]}]}],
                provider={"type": "fake", "promptVersion": "summary-v1"},
            ),
        )

        self.assertEqual(["item-primary", "item-related"], briefing["sourceItemIds"])
        self.assertEqual(["primary-source", "related-source"], [citation["sourceId"] for citation in briefing["citations"]])


if __name__ == "__main__":
    unittest.main()

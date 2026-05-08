from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from wazzup.ai import SummaryResponse
from wazzup.models import AppConfig, ContentItem, ScoredItem, SourceStatus
from wazzup.publisher import build_briefing, build_run_status, enforce_retention, write_data, write_manifest


class PublisherTests(unittest.TestCase):
    def test_retention_uses_data_path_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            old_article = data_dir / "articles" / "2026" / "03" / "01.yaml"
            current_article = data_dir / "articles" / "2026" / "05" / "06.yaml"
            old_briefing = data_dir / "briefings" / "2026" / "03" / "01" / "hourly-10.yaml"
            current_briefing = data_dir / "briefings" / "2026" / "05" / "06" / "hourly-10.yaml"
            for path in [old_article, current_article, old_briefing, current_briefing]:
                write_data(path, {"ok": True})

            enforce_retention(data_dir, datetime(2026, 5, 6, tzinfo=UTC), 35)
            write_manifest(data_dir, datetime(2026, 5, 6, tzinfo=UTC), 35)

            self.assertFalse(old_article.exists())
            self.assertFalse(old_article.with_suffix(".json").exists())
            self.assertFalse(old_briefing.exists())
            self.assertFalse(old_briefing.with_suffix(".json").exists())
            self.assertTrue(current_article.exists())
            self.assertTrue(current_article.with_suffix(".json").exists())
            self.assertTrue(current_briefing.exists())
            self.assertTrue(current_briefing.with_suffix(".json").exists())
            manifest = (data_dir / "manifest.yaml").read_text(encoding="utf-8")
            self.assertIn("articles/2026/05/06.yaml", manifest)
            self.assertIn("briefings/2026/05/06/hourly-10.yaml", manifest)
            self.assertNotIn("2026/03", manifest)

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

    def test_build_run_status_keeps_last_successful_on_degraded_run(self) -> None:
        first_generated_at = datetime(2026, 5, 6, 9, tzinfo=UTC)
        first_status = build_run_status(
            "hourly",
            first_generated_at,
            [],
            SummaryResponse(headline="ok", sections=[{"title": "Top", "bullets": []}], provider={"type": "fake"}),
            [SourceStatus("one", True, "2026-05-06T09:00:00Z", 1, "ok")],
            0,
            {},
        )
        second_generated_at = datetime(2026, 5, 6, 10, tzinfo=UTC)
        second_status = build_run_status(
            "hourly",
            second_generated_at,
            [],
            SummaryResponse(headline="degraded", sections=[{"title": "Top", "bullets": []}], provider={"type": "fake"}),
            [SourceStatus("one", False, "2026-05-06T10:00:00Z", 0, "timeout")],
            1,
            {"runStatus": first_status},
        )

        self.assertEqual("ok", first_status["status"])
        self.assertEqual("degraded_sources", second_status["status"])
        self.assertEqual("2026-05-06T10:00:00Z", second_status["lastAttemptedRunAt"])
        self.assertEqual("2026-05-06T09:00:00Z", second_status["lastSuccessfulRunAt"])


if __name__ == "__main__":
    unittest.main()

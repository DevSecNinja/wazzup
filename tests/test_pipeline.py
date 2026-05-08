from __future__ import annotations

import os
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from wazzup.models import ContentItem, ScoredItem
from wazzup.pipeline import (
    exclude_already_featured_hourly_items,
    featured_hourly_item_ids_for_local_day,
    generate,
    prioritize_hourly_new_items,
)
from wazzup.validate_data import validate_data_dir


def scored_item(item_id: str, published_at: str, score: float) -> ScoredItem:
    return ScoredItem(
        item=ContentItem(
            schema_version=1,
            id=item_id,
            source_id="test-source",
            source_name="Test Source",
            source_tag="Test",
            source_type="rss",
            title=f"Article {item_id}",
            url=f"https://example.com/{item_id}",
            canonical_url=f"https://example.com/{item_id}",
            published_at=published_at,
            discovered_at=published_at,
            authors=[],
            tags=[],
            language="en",
            summary="Summary",
            content_hash=item_id,
            raw_ref=item_id,
        ),
        score=score,
        score_reasons=[],
        matched_interests=[],
        duplicate_group_id=f"dup-{item_id}",
        freshness_bucket="fresh",
    )


def content_item(item_id: str, source_id: str, title: str, canonical_url: str, published_at: str, summary: str) -> ContentItem:
    return ContentItem(
        schema_version=1,
        id=item_id,
        source_id=source_id,
        source_name=f"{source_id} name",
        source_tag=source_id.upper(),
        source_type="rss",
        title=title,
        url=canonical_url,
        canonical_url=canonical_url,
        published_at=published_at,
        discovered_at=published_at,
        authors=[],
        tags=["security"],
        language="en",
        summary=summary,
        content_hash=f"hash-{item_id}",
        raw_ref=item_id,
    )


class PipelineTests(unittest.TestCase):
    def test_hourly_selection_prioritizes_new_articles(self) -> None:
        now = datetime(2026, 5, 6, 15, 42, tzinfo=UTC)
        scored = [
            scored_item("older-high", "2026-05-06T09:00:00Z", 99),
            scored_item("newest", "2026-05-06T15:35:00Z", 10),
            scored_item("newer", "2026-05-06T15:20:00Z", 10),
            scored_item("new", "2026-05-06T15:05:00Z", 10),
            scored_item("hour-old", "2026-05-06T14:50:00Z", 10),
            scored_item("older-low", "2026-05-06T08:00:00Z", 1),
        ]

        prioritized = prioritize_hourly_new_items(scored, now)

        self.assertEqual(["newest", "newer", "new", "hour-old"], [item.item.id for item in prioritized[:4]])
        self.assertEqual("older-high", prioritized[4].item.id)

    def test_generate_auto_selects_due_morning_briefing(self) -> None:
        previous_provider = os.environ.get("AI_PROVIDER")
        os.environ["AI_PROVIDER"] = "fake"
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                public_dir = Path(tmp_dir)
                fixed_now = datetime(2026, 5, 6, 5, 10, tzinfo=UTC)
                with patch("wazzup.pipeline.utc_now", return_value=fixed_now):
                    latest = generate(
                        [
                            "--fixture-dir",
                            "tests/fixtures",
                            "--public-dir",
                            str(public_dir),
                            "--force-briefing",
                            "auto",
                        ]
                    )
                self.assertTrue(latest["latestBriefingUrl"].endswith("/morning.json"))
                briefing = json.loads((public_dir / latest["latestBriefingUrl"]).read_text(encoding="utf-8"))
                self.assertEqual("morning", briefing["kind"])
        finally:
            if previous_provider is None:
                os.environ.pop("AI_PROVIDER", None)
            else:
                os.environ["AI_PROVIDER"] = previous_provider

    def test_generate_auto_skips_existing_due_morning_briefing(self) -> None:
        previous_provider = os.environ.get("AI_PROVIDER")
        os.environ["AI_PROVIDER"] = "fake"
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                public_dir = Path(tmp_dir)
                fixed_now = datetime(2026, 5, 6, 5, 10, tzinfo=UTC)
                with patch("wazzup.pipeline.utc_now", return_value=fixed_now):
                    generate(
                        [
                            "--fixture-dir",
                            "tests/fixtures",
                            "--public-dir",
                            str(public_dir),
                            "--force-briefing",
                            "morning",
                        ]
                    )
                with patch("wazzup.pipeline.utc_now", return_value=fixed_now):
                    latest = generate(
                        [
                            "--fixture-dir",
                            "tests/fixtures",
                            "--public-dir",
                            str(public_dir),
                            "--force-briefing",
                            "auto",
                        ]
                    )
                briefing = json.loads((public_dir / latest["latestBriefingUrl"]).read_text(encoding="utf-8"))
                self.assertEqual("hourly", briefing["kind"])
                self.assertTrue((latest.get("latestMorningBriefingUrl") or "").endswith("/morning.json"))
        finally:
            if previous_provider is None:
                os.environ.pop("AI_PROVIDER", None)
            else:
                os.environ["AI_PROVIDER"] = previous_provider

    def test_generate_static_data_from_fixtures(self) -> None:
        previous_provider = os.environ.get("AI_PROVIDER")
        os.environ["AI_PROVIDER"] = "fake"
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                public_dir = Path(tmp_dir)
                # Copy static PWA shell because pipeline writes only data files.
                fixed_now = datetime(2026, 5, 6, 18, 0, tzinfo=UTC)
                with patch("wazzup.pipeline.utc_now", return_value=fixed_now):
                    latest = generate(
                        [
                            "--fixture-dir",
                            "tests/fixtures",
                            "--public-dir",
                            str(public_dir),
                            "--force-briefing",
                            "hourly",
                        ]
                    )
                self.assertIn("latestBriefingUrl", latest)
                self.assertIn("latestArticlesUrl", latest)
                self.assertTrue(latest["latestBriefingUrl"].startswith("data/"))
                self.assertTrue(latest["latestArticlesUrl"].startswith("data/"))
                validate_data_dir(public_dir / "data")
                briefing_path = public_dir / latest["latestBriefingUrl"]
                articles_path = public_dir / latest["latestArticlesUrl"]
                briefing = briefing_path.read_text(encoding="utf-8")
                self.assertIn("Top updates", briefing)
                briefing_json = json.loads(briefing_path.read_text(encoding="utf-8"))
                articles_text = articles_path.read_text(encoding="utf-8")
                articles_json = json.loads(articles_text)
                self.assertEqual("2026-05-05T22:00:00Z", briefing_json["windowStart"])
                self.assertEqual("2026-05-06T18:00:00Z", briefing_json["windowEnd"])
                self.assertIsInstance(articles_json["items"], list)
                self.assertTrue(articles_text.lstrip().startswith("{"))
                self.assertIn("publishedAt", briefing_json["citations"][0])
                self.assertIn("sourceTag", briefing_json["citations"][0])
                self.assertIn("tags", briefing_json["citations"][0])
                self.assertIn("temperature", briefing_json["citations"][0])
                self.assertIn(briefing_json["citations"][0]["temperature"]["level"], {"hot", "warm", "cool"})
                self.assertIn("title", briefing_json["sections"][0]["bullets"][0])
                self.assertIn("description", briefing_json["sections"][0]["bullets"][0])
                status_json = json.loads((public_dir / "data" / "sources" / "status.json").read_text(encoding="utf-8"))
                self.assertTrue(all("lastArticleAt" in source for source in status_json["sources"]))
        finally:
            if previous_provider is None:
                os.environ.pop("AI_PROVIDER", None)
            else:
                os.environ["AI_PROVIDER"] = previous_provider

    def test_generate_hourly_excludes_items_featured_earlier_today(self) -> None:
        previous_provider = os.environ.get("AI_PROVIDER")
        os.environ["AI_PROVIDER"] = "fake"
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                public_dir = Path(tmp_dir)
                first_run_now = datetime(2026, 5, 6, 16, 0, tzinfo=UTC)
                with patch("wazzup.pipeline.utc_now", return_value=first_run_now):
                    first_latest = generate(
                        [
                            "--fixture-dir",
                            "tests/fixtures",
                            "--public-dir",
                            str(public_dir),
                            "--force-briefing",
                            "hourly",
                            "--max-items",
                            "2",
                        ]
                    )
                first_briefing = json.loads((public_dir / first_latest["latestBriefingUrl"]).read_text(encoding="utf-8"))
                first_ids = first_briefing["sourceItemIds"]
                self.assertEqual(2, len(first_ids))

                second_run_now = datetime(2026, 5, 6, 17, 0, tzinfo=UTC)
                with patch("wazzup.pipeline.utc_now", return_value=second_run_now):
                    second_latest = generate(
                        [
                            "--fixture-dir",
                            "tests/fixtures",
                            "--public-dir",
                            str(public_dir),
                            "--force-briefing",
                            "hourly",
                            "--max-items",
                            "2",
                        ]
                    )
                second_briefing = json.loads((public_dir / second_latest["latestBriefingUrl"]).read_text(encoding="utf-8"))
                second_ids = second_briefing["sourceItemIds"]
                self.assertTrue(second_ids)
                self.assertTrue(set(first_ids).isdisjoint(second_ids))
        finally:
            if previous_provider is None:
                os.environ.pop("AI_PROVIDER", None)
            else:
                os.environ["AI_PROVIDER"] = previous_provider

    def test_featured_hourly_item_ids_for_local_day_reads_source_item_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir) / "data"
            briefing_dir = data_dir / "briefings" / "2026" / "05" / "06"
            briefing_dir.mkdir(parents=True)
            (briefing_dir / "hourly-08.json").write_text(
                json.dumps({"sourceItemIds": ["item-1", "item-2"]}),
                encoding="utf-8",
            )
            (briefing_dir / "hourly-09.json").write_text(
                json.dumps({"sourceItemIds": ["item-2", "item-3"]}),
                encoding="utf-8",
            )
            now = datetime(2026, 5, 6, 10, 0, tzinfo=UTC)

            featured_ids = featured_hourly_item_ids_for_local_day(data_dir, now, "UTC")

            self.assertEqual({"item-1", "item-2", "item-3"}, featured_ids)

    def test_exclude_already_featured_hourly_items_falls_back_when_no_fresh(self) -> None:
        scored = [scored_item("item-1", "2026-05-06T09:00:00Z", 10), scored_item("item-2", "2026-05-06T08:00:00Z", 8)]

        same_items = exclude_already_featured_hourly_items(scored, {"item-1", "item-2"})

        self.assertEqual(["item-1", "item-2"], [item.item.id for item in same_items])

    def test_exclude_already_featured_hourly_items_keeps_mixed_new_related_groups(self) -> None:
        related = ContentItem(
            schema_version=1,
            id="related-featured",
            source_id="related-source",
            source_name="Related Source",
            source_tag="Related",
            source_type="rss",
            title="Related article",
            url="https://example.com/related-featured",
            canonical_url="https://example.com/related-featured",
            published_at="2026-05-06T09:00:00Z",
            discovered_at="2026-05-06T09:00:00Z",
            authors=[],
            tags=[],
            language="en",
            summary="Related summary",
            content_hash="related-featured",
            raw_ref="related-featured",
        )
        correlated = scored_item("item-1", "2026-05-06T09:00:00Z", 10)
        correlated = replace(correlated, item=replace(correlated.item, related_items=(related,)))
        other = scored_item("item-2", "2026-05-06T08:00:00Z", 8)

        fresh_items = exclude_already_featured_hourly_items([correlated, other], {"related-featured", "item-2"})

        self.assertEqual(["item-1"], [item.item.id for item in fresh_items])

    def test_exclude_already_featured_hourly_items_drops_fully_featured_related_groups(self) -> None:
        related = ContentItem(
            schema_version=1,
            id="related-featured",
            source_id="related-source",
            source_name="Related Source",
            source_tag="Related",
            source_type="rss",
            title="Related article",
            url="https://example.com/related-featured",
            canonical_url="https://example.com/related-featured",
            published_at="2026-05-06T09:00:00Z",
            discovered_at="2026-05-06T09:00:00Z",
            authors=[],
            tags=[],
            language="en",
            summary="Related summary",
            content_hash="related-featured",
            raw_ref="related-featured",
        )
        correlated = scored_item("item-1", "2026-05-06T09:00:00Z", 10)
        correlated = replace(correlated, item=replace(correlated.item, related_items=(related,)))
        other = scored_item("item-2", "2026-05-06T08:00:00Z", 8)

        fresh_items = exclude_already_featured_hourly_items([correlated, other], {"item-1", "related-featured"})

        self.assertEqual(["item-2"], [item.item.id for item in fresh_items])

    def test_generate_clusters_related_story_items_before_ai_summary(self) -> None:
        previous_provider = os.environ.get("AI_PROVIDER")
        os.environ["AI_PROVIDER"] = "fake"
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                public_dir = Path(tmp_dir)
                fixed_now = datetime(2026, 5, 6, 10, 30, tzinfo=UTC)
                grouped_items = [
                    content_item(
                        "item-primary",
                        "source-a",
                        "Acme VPN CVE-2026-4242 exploited in active campaign",
                        "https://example.com/security/acme-vpn-cve-2026-4242",
                        "2026-05-06T09:20:00Z",
                        "Researchers report active exploitation of Acme VPN CVE-2026-4242.",
                    ),
                    content_item(
                        "item-related",
                        "source-b",
                        "Emergency patch for Acme VPN after CVE-2026-4242 exploitation",
                        "https://example.net/alerts/acme-vpn-cve-2026-4242-patch",
                        "2026-05-06T09:45:00Z",
                        "Vendors ship fixes for the same Acme VPN CVE-2026-4242 campaign.",
                    ),
                ]
                with (
                    patch("wazzup.pipeline.utc_now", return_value=fixed_now),
                    patch(
                        "wazzup.pipeline.collect_items",
                        return_value=(
                            grouped_items,
                            [],
                            [],
                        ),
                    ),
                ):
                    latest = generate(
                        [
                            "--public-dir",
                            str(public_dir),
                            "--force-briefing",
                            "hourly",
                            "--max-items",
                            "5",
                        ]
                    )
                briefing = json.loads((public_dir / latest["latestBriefingUrl"]).read_text(encoding="utf-8"))
                articles = json.loads((public_dir / latest["latestArticlesUrl"]).read_text(encoding="utf-8"))

                self.assertEqual(1, len(articles["items"]))
                self.assertEqual({"item-primary", "item-related"}, set(briefing["sourceItemIds"]))
                self.assertEqual(1, len(briefing["sections"][0]["bullets"]))
                self.assertEqual({"item-primary", "item-related"}, set(briefing["sections"][0]["bullets"][0]["citations"]))
        finally:
            if previous_provider is None:
                os.environ.pop("AI_PROVIDER", None)
            else:
                os.environ["AI_PROVIDER"] = previous_provider


if __name__ == "__main__":
    unittest.main()

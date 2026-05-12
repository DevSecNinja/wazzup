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
    content_window,
    curated_scored_items,
    diversification_key,
    diversify_scored_items,
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


class PipelineTests(unittest.TestCase):
    def test_morning_content_window_starts_at_local_midnight(self) -> None:
        now = datetime(2026, 5, 10, 5, 10, tzinfo=UTC)

        window_start, window_end = content_window("morning", now, "Europe/Amsterdam")

        self.assertEqual("2026-05-09T22:00:00+00:00", window_start.isoformat())
        self.assertEqual("2026-05-10T05:00:00+00:00", window_end.isoformat())

    def test_diversification_key_prefers_interest_and_falls_back_to_source(self) -> None:
        interested = replace(scored_item("interested", "2026-05-06T15:35:00Z", 50), matched_interests=["motorsport"])
        uninterested = scored_item("uninterested", "2026-05-06T15:34:00Z", 49)
        uninterested = replace(uninterested, item=replace(uninterested.item, source_id="source-b"))

        self.assertEqual("interest:motorsport", diversification_key(interested))
        self.assertEqual("source:source-b", diversification_key(uninterested))

    def test_diversify_scored_items_limits_interest_streaks(self) -> None:
        motorsport_1 = replace(scored_item("motorsport-1", "2026-05-06T15:35:00Z", 50), matched_interests=["motorsport"])
        motorsport_2 = replace(scored_item("motorsport-2", "2026-05-06T15:34:00Z", 49), matched_interests=["motorsport"])
        motorsport_3 = replace(scored_item("motorsport-3", "2026-05-06T15:33:00Z", 48), matched_interests=["motorsport"])
        security = replace(scored_item("security-1", "2026-05-06T15:32:00Z", 47), matched_interests=["security"])
        ai = replace(scored_item("ai-1", "2026-05-06T15:31:00Z", 46), matched_interests=["ai"])

        diversified = diversify_scored_items([motorsport_1, motorsport_2, motorsport_3, security, ai], max_consecutive=2)

        self.assertEqual(["motorsport-1", "motorsport-2", "security-1", "motorsport-3", "ai-1"], [item.item.id for item in diversified])

    def test_diversify_scored_items_uses_source_id_without_interest_matches(self) -> None:
        source_a_1 = scored_item("source-a-1", "2026-05-06T15:35:00Z", 50)
        source_a_2 = scored_item("source-a-2", "2026-05-06T15:34:00Z", 49)
        source_a_3 = scored_item("source-a-3", "2026-05-06T15:33:00Z", 48)
        source_b_base = scored_item("source-b-1", "2026-05-06T15:32:00Z", 47)
        source_b = replace(source_b_base, item=replace(source_b_base.item, source_id="source-b"))

        diversified = diversify_scored_items([source_a_1, source_a_2, source_a_3, source_b], max_consecutive=2)

        self.assertEqual(["source-a-1", "source-a-2", "source-b-1", "source-a-3"], [item.item.id for item in diversified])

    def test_diversify_scored_items_returns_input_when_threshold_or_length_short_circuits(self) -> None:
        first = scored_item("first", "2026-05-06T15:35:00Z", 50)
        second = scored_item("second", "2026-05-06T15:34:00Z", 49)

        self.assertEqual([], diversify_scored_items([], max_consecutive=2))
        self.assertEqual([first], diversify_scored_items([first], max_consecutive=0))
        self.assertEqual([first, second], diversify_scored_items([first, second], max_consecutive=2))

    def test_curated_scored_items_keeps_known_unique_ids_up_to_max(self) -> None:
        first = scored_item("first", "2026-05-06T15:35:00Z", 50)
        second = scored_item("second", "2026-05-06T15:34:00Z", 49)
        third = scored_item("third", "2026-05-06T15:33:00Z", 48)

        curated = curated_scored_items([first, second, third], ["unknown", "second", "second", "third", "first"], 2)

        self.assertEqual(["second", "third"], [item.item.id for item in curated])

    def test_curated_scored_items_falls_back_when_selection_is_empty(self) -> None:
        first = scored_item("first", "2026-05-06T15:35:00Z", 50)
        second = scored_item("second", "2026-05-06T15:34:00Z", 49)

        curated = curated_scored_items([first, second], ["unknown"], 1)

        self.assertEqual(["first"], [item.item.id for item in curated])
        self.assertEqual([], curated_scored_items([], ["unknown"], 1))
        self.assertEqual([], curated_scored_items([first, second], ["first"], 0))

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
                self.assertIn("latestTransparencyReportUrl", latest)
                self.assertIn("latestTransparencyReportMarkdownUrl", latest)
                self.assertTrue(latest["latestBriefingUrl"].startswith("data/"))
                self.assertTrue(latest["latestArticlesUrl"].startswith("data/"))
                self.assertTrue(latest["latestTransparencyReportUrl"].startswith("data/"))
                validate_data_dir(public_dir / "data")
                briefing_path = public_dir / latest["latestBriefingUrl"]
                articles_path = public_dir / latest["latestArticlesUrl"]
                transparency_path = public_dir / latest["latestTransparencyReportUrl"]
                transparency_markdown_path = public_dir / latest["latestTransparencyReportMarkdownUrl"]
                briefing = briefing_path.read_text(encoding="utf-8")
                self.assertIn("Top updates", briefing)
                briefing_json = json.loads(briefing_path.read_text(encoding="utf-8"))
                articles_text = articles_path.read_text(encoding="utf-8")
                articles_json = json.loads(articles_text)
                transparency_json = json.loads(transparency_path.read_text(encoding="utf-8"))
                self.assertEqual("2026-05-05T22:00:00Z", briefing_json["windowStart"])
                self.assertEqual("2026-05-06T18:00:00Z", briefing_json["windowEnd"])
                self.assertIsInstance(articles_json["items"], list)
                self.assertEqual("transparency-v1", transparency_json["promptVersion"])
                self.assertTrue(transparency_markdown_path.read_text(encoding="utf-8").startswith("# Transparency report"))
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


if __name__ == "__main__":
    unittest.main()

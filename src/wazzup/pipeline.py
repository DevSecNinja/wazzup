from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from .ai import SummaryRequest, provider_from_env
from .config import load_app_config, load_sources
from .feeds import deduplicate, fetch_and_parse, isoformat, parse_feed, utc_now
from .models import BriefingKind, ContentItem, ScoredItem, SourceStatus
from .publisher import briefing_path, publish_outputs
from .scoring import parse_iso, score_items


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Wazzup static briefing data")
    parser.add_argument("--sources", default="config/sources.yml", help="Path to sources YAML")
    parser.add_argument("--interests", default="config/interests.yml", help="Path to interests YAML")
    parser.add_argument("--public-dir", default="public", help="Public output directory")
    parser.add_argument(
        "--force-briefing",
        choices=["auto", "none", "hourly", "morning", "evening"],
        default="auto",
        help="Briefing kind to generate; auto selects due morning/evening in local time",
    )
    parser.add_argument("--fixture-dir", default="", help="Optional directory with <source-id>.xml fixtures")
    parser.add_argument("--max-items", type=int, default=int(os.environ.get("WAZZUP_MAX_AI_ITEMS", "12")))
    return parser.parse_args(argv)


def _local_time_parts(value: str) -> tuple[int, int]:
    hour, minute = value.split(":", maxsplit=1)
    return int(hour), int(minute)


def _is_due(local_now: datetime, local_target: datetime) -> bool:
    return local_target <= local_now < (local_target + timedelta(hours=2))


def _briefing_already_exists(public_dir: Path, kind: BriefingKind, now: datetime, timezone: str) -> bool:
    _, window_end = briefing_window(kind, now, timezone)
    data_dir = public_dir / "data"
    path = briefing_path(data_dir, kind, window_end)
    return path.exists() or path.with_suffix(".json").exists()


def choose_kind(force_briefing: str, now: datetime, timezone: str, public_dir: Path, morning_time: str, evening_time: str) -> BriefingKind:
    if force_briefing in {"morning", "evening", "hourly"}:
        return force_briefing  # type: ignore[return-value]
    local_now = now.astimezone(ZoneInfo(timezone))
    morning_hour, morning_minute = _local_time_parts(morning_time)
    evening_hour, evening_minute = _local_time_parts(evening_time)
    morning_target = local_now.replace(hour=morning_hour, minute=morning_minute, second=0, microsecond=0)
    evening_target = local_now.replace(hour=evening_hour, minute=evening_minute, second=0, microsecond=0)
    if _is_due(local_now, morning_target) and not _briefing_already_exists(public_dir, "morning", now, timezone):
        return "morning"
    if _is_due(local_now, evening_target) and not _briefing_already_exists(public_dir, "evening", now, timezone):
        return "evening"
    return "hourly"


def briefing_window(kind: BriefingKind, now: datetime, timezone: str) -> tuple[datetime, datetime]:
    local_now = now.astimezone(ZoneInfo(timezone))
    if kind == "morning":
        local_end = local_now.replace(hour=7, minute=0, second=0, microsecond=0)
        if local_now < local_end:
            local_end -= timedelta(days=1)
        local_start = (local_end - timedelta(days=1)).replace(hour=20)
    elif kind == "evening":
        local_end = local_now.replace(hour=20, minute=0, second=0, microsecond=0)
        if local_now < local_end:
            local_end -= timedelta(days=1)
        local_start = local_end.replace(hour=7)
    else:
        local_end = local_now.replace(minute=0, second=0, microsecond=0)
        local_start = local_end - timedelta(hours=1)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)


def rolling_day_window(now: datetime, timezone: str) -> tuple[datetime, datetime]:
    local_now = now.astimezone(ZoneInfo(timezone))
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(UTC), now.astimezone(UTC)


def filter_items_to_window(items: list[ContentItem], window_start: datetime, window_end: datetime) -> list[ContentItem]:
    return [item for item in items if window_start <= parse_iso(item.published_at) <= window_end]


def prioritize_hourly_new_items(scored_items: list[ScoredItem], now: datetime) -> list[ScoredItem]:
    recent_start = now.astimezone(UTC) - timedelta(hours=1)
    recent_end = now.astimezone(UTC)
    recent_items = []
    older_items = []
    for scored in scored_items:
        published_at = parse_iso(scored.item.published_at)
        if recent_start <= published_at <= recent_end:
            recent_items.append(scored)
        else:
            older_items.append(scored)
    # New hourly articles stay above older high-scoring items; score only breaks ties among recent items.
    return sorted(recent_items, key=lambda scored: (parse_iso(scored.item.published_at), scored.score), reverse=True) + older_items


def load_items_from_fixture(source_id: str, fixture_dir: Path, source) -> list[ContentItem] | None:
    fixture_path = fixture_dir / f"{source_id}.xml"
    if not fixture_path.exists():
        return None
    return parse_feed(source, fixture_path.read_bytes(), utc_now())


def collect_items(sources_path: str, fixture_dir: str = "") -> tuple[list[ContentItem], list[SourceStatus], list]:
    sources = load_sources(sources_path)
    enabled_sources = [source for source in sources if source.enabled]
    all_items: list[ContentItem] = []
    statuses: list[SourceStatus] = []
    fixture_root = Path(fixture_dir) if fixture_dir else None
    discovered_at = utc_now()
    for source in enabled_sources:
        fixture_items = load_items_from_fixture(source.id, fixture_root, source) if fixture_root else None
        if fixture_items is not None:
            all_items.extend(fixture_items)
            last_article_at = max((item.published_at for item in fixture_items), default=None)
            statuses.append(SourceStatus(source.id, True, isoformat(discovered_at), len(fixture_items), "fixture", last_article_at))
            continue
        items, status = fetch_and_parse(source, discovered_at)
        all_items.extend(items)
        statuses.append(status)
    return deduplicate(all_items), statuses, enabled_sources


def generate(argv: Sequence[str] | None = None) -> dict:
    args = parse_args(argv)
    app_config = load_app_config(args.interests)
    items, statuses, sources = collect_items(args.sources, args.fixture_dir)
    now = utc_now()
    kind = choose_kind(
        args.force_briefing,
        now,
        app_config.timezone,
        Path(args.public_dir),
        app_config.morning_local_time,
        app_config.evening_local_time,
    )
    window_start, window_end = briefing_window(kind, now, app_config.timezone)
    content_window_start = window_start
    content_window_end = window_end
    if kind == "hourly":
        content_window_start, content_window_end = rolling_day_window(now, app_config.timezone)
    window_items = filter_items_to_window(items, content_window_start, content_window_end)
    scored = score_items(window_items, sources, app_config, now)
    if kind == "hourly":
        scored = prioritize_hourly_new_items(scored, now)
    scored = scored[: args.max_items]
    provider = provider_from_env(app_config)
    summary = provider.generate_structured_summary(
        SummaryRequest(
            kind=kind,
            window_start=isoformat(content_window_start),
            window_end=isoformat(content_window_end),
            generated_at=isoformat(now),
            timezone=app_config.timezone,
            summary_language=app_config.summary_language,
            items=scored,
        )
    )
    latest = publish_outputs(
        Path(args.public_dir),
        kind,
        content_window_start,
        content_window_end,
        now,
        app_config,
        scored,
        summary,
        statuses,
    )
    return latest


def main(argv: Sequence[str] | None = None) -> None:
    latest = generate(argv)
    print(json.dumps(latest, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

from datetime import UTC, datetime

from .feeds import stable_hash
from .models import AppConfig, ContentItem, ScoredItem, SourceConfig


def parse_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def freshness_bucket(age_hours: float) -> str:
    if age_hours <= 2:
        return "breaking"
    if age_hours <= 12:
        return "fresh"
    if age_hours <= 48:
        return "recent"
    return "older"


def score_items(
    items: list[ContentItem],
    sources: list[SourceConfig],
    app_config: AppConfig,
    now: datetime,
) -> list[ScoredItem]:
    source_by_id = {source.id: source for source in sources}
    scored: list[ScoredItem] = []
    for item in items:
        source = source_by_id.get(item.source_id)
        source_weight = source.weight if source else 1.0
        haystack = " ".join([item.title, item.summary, " ".join(item.tags)]).lower()
        matched_interests: list[str] = []
        reasons: list[str] = []
        score = 10.0 * source_weight
        if source_weight != 1.0:
            reasons.append(f"source weight {source_weight:g}")

        for interest in app_config.interests:
            matches = [keyword for keyword in interest.keywords if keyword.lower() in haystack]
            if matches:
                increment = min(len(matches), 3) * 4.0 * interest.weight
                score += increment
                if interest.weight >= 0:
                    matched_interests.append(interest.id)
                    reasons.append(f"matches {interest.name}: {', '.join(matches[:3])}")
                else:
                    reasons.append(f"demotes {interest.name}: {', '.join(matches[:3])}")

        published = parse_iso(item.published_at)
        age_hours = max((now - published).total_seconds() / 3600, 0)
        bucket = freshness_bucket(age_hours)
        recency_bonus = max(0.0, 8.0 - min(age_hours, 72.0) / 9.0)
        score += recency_bonus
        reasons.append(f"{bucket} item")

        if item.source_id == "microsoft-security-threat-intelligence":
            score += 6.0
            reasons.append("priority threat intelligence source")

        duplicate_group_id = f"dup-{stable_hash(*sorted([item.id, *(related.id for related in item.related_items)]))}"
        scored.append(
            ScoredItem(
                item=item,
                score=score,
                score_reasons=reasons,
                matched_interests=matched_interests,
                duplicate_group_id=duplicate_group_id,
                freshness_bucket=bucket,
            )
        )
    return sorted(scored, key=lambda scored_item: scored_item.score, reverse=True)

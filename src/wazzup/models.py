from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SourceType = Literal["rss", "atom", "json-feed", "podcast"]
BriefingKind = Literal["hourly", "morning", "evening", "manual"]


@dataclass(frozen=True)
class SourceConfig:
    id: str
    name: str
    source_tag: str
    type: SourceType
    homepage_url: str
    feed_url: str
    language: str
    region: str
    weight: float
    categories: list[str] = field(default_factory=list)
    interest_hints: list[str] = field(default_factory=list)
    enabled: bool = True
    headers: dict[str, str] = field(default_factory=dict)
    notes: str | None = None


@dataclass(frozen=True)
class Interest:
    id: str
    name: str
    weight: float
    keywords: list[str]


@dataclass(frozen=True)
class AppConfig:
    summary_language: str
    retention_days: int
    timezone: str
    morning_local_time: str
    evening_local_time: str
    interests: list[Interest]


@dataclass(frozen=True)
class ContentItem:
    schema_version: int
    id: str
    source_id: str
    source_name: str
    source_tag: str
    source_type: SourceType
    title: str
    url: str
    canonical_url: str
    published_at: str
    discovered_at: str
    authors: list[str]
    tags: list[str]
    language: str
    summary: str
    content_hash: str
    raw_ref: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "id": self.id,
            "sourceId": self.source_id,
            "sourceName": self.source_name,
            "sourceTag": self.source_tag,
            "sourceType": self.source_type,
            "title": self.title,
            "url": self.url,
            "canonicalUrl": self.canonical_url,
            "publishedAt": self.published_at,
            "discoveredAt": self.discovered_at,
            "authors": self.authors,
            "tags": self.tags,
            "language": self.language,
            "summary": self.summary,
            "contentHash": self.content_hash,
            "rawRef": self.raw_ref,
        }


@dataclass(frozen=True)
class ScoredItem:
    item: ContentItem
    score: float
    score_reasons: list[str]
    matched_interests: list[str]
    duplicate_group_id: str
    freshness_bucket: str

    def to_dict(self) -> dict[str, Any]:
        payload = self.item.to_dict()
        payload.update(
            {
                "score": round(self.score, 3),
                "scoreReasons": self.score_reasons,
                "matchedInterests": self.matched_interests,
                "duplicateGroupId": self.duplicate_group_id,
                "freshnessBucket": self.freshness_bucket,
            }
        )
        return payload


@dataclass(frozen=True)
class SourceStatus:
    source_id: str
    ok: bool
    fetched_at: str
    item_count: int
    message: str
    last_article_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "ok": self.ok,
            "fetchedAt": self.fetched_at,
            "itemCount": self.item_count,
            "message": self.message,
            "lastArticleAt": self.last_article_at,
        }

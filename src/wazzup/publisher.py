from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .ai import SummaryResponse
from .feeds import isoformat, stable_hash
from .models import AppConfig, BriefingKind, ScoredItem, SourceStatus


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def write_json_mirror(path: Path, payload: dict[str, Any]) -> None:
    import json

    json_path = path.with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_data(path: Path, payload: dict[str, Any]) -> None:
    write_yaml(path, payload)
    write_json_mirror(path, payload)


def date_parts(dt: datetime) -> tuple[str, str, str]:
    return f"{dt:%Y}", f"{dt:%m}", f"{dt:%d}"


def build_briefing(
    kind: BriefingKind,
    window_start: datetime,
    window_end: datetime,
    generated_at: datetime,
    app_config: AppConfig,
    scored_items: list[ScoredItem],
    summary: SummaryResponse,
) -> dict[str, Any]:
    briefing_id = f"briefing-{kind}-{stable_hash(isoformat(window_start), isoformat(window_end), summary.headline)}"
    citations = []
    scored_by_id = {scored.item.id: scored for scored in scored_items}
    for item_id, scored in scored_by_id.items():
        item = scored.item
        citations.append(
            {
                "itemId": item_id,
                "title": item.title,
                "url": item.url,
                "sourceId": item.source_id,
                "sourceName": item.source_name,
                "sourceTag": item.source_tag,
                "tags": item.tags,
                "publishedAt": item.published_at,
                "temperature": article_temperature(scored),
            }
        )
    provider = summary.provider
    return {
        "schemaVersion": 1,
        "id": briefing_id,
        "kind": kind,
        "windowStart": isoformat(window_start),
        "windowEnd": isoformat(window_end),
        "generatedAt": isoformat(generated_at),
        "timezone": app_config.timezone,
        "language": app_config.summary_language,
        "headline": summary.headline,
        "sections": summary.sections,
        "sourceItemIds": [scored.item.id for scored in scored_items],
        "citations": citations,
        "model": provider.get("model", "unknown"),
        "provider": provider,
        "promptVersion": provider.get("promptVersion", "summary-v1"),
        "costEstimate": provider.get("costEstimate", {"amount": 0, "currency": "USD"}),
    }


def article_temperature(scored: ScoredItem) -> dict[str, Any]:
    if scored.score >= 34:
        return {"level": "hot", "label": "High priority", "icon": "🔥"}
    if scored.score >= 24:
        return {"level": "warm", "label": "Worth knowing", "icon": "⚡"}
    return {"level": "cool", "label": "Background", "icon": "•"}


def briefing_path(data_dir: Path, kind: BriefingKind, window_end: datetime) -> Path:
    year, month, day = date_parts(window_end)
    if kind == "hourly":
        filename = f"hourly-{window_end:%H}.yaml"
    else:
        filename = f"{kind}.yaml"
    return data_dir / "briefings" / year / month / day / filename


def articles_path(data_dir: Path, window_end: datetime) -> Path:
    year, month, day = date_parts(window_end)
    return data_dir / "articles" / year / month / f"{day}.yaml"


def publish_outputs(
    public_dir: Path,
    kind: BriefingKind,
    window_start: datetime,
    window_end: datetime,
    generated_at: datetime,
    app_config: AppConfig,
    scored_items: list[ScoredItem],
    summary: SummaryResponse,
    statuses: list[SourceStatus],
) -> dict[str, Any]:
    data_dir = public_dir / "data"
    public_dir.mkdir(parents=True, exist_ok=True)
    briefing = build_briefing(kind, window_start, window_end, generated_at, app_config, scored_items, summary)
    b_path = briefing_path(data_dir, kind, window_end)
    a_path = articles_path(data_dir, window_end)
    write_data(b_path, briefing)
    write_data(
        a_path,
        {
            "schemaVersion": 1,
            "generatedAt": isoformat(generated_at),
            "items": [scored.to_dict() for scored in scored_items],
        },
    )
    write_data(
        data_dir / "sources" / "status.yaml",
        {
            "schemaVersion": 1,
            "generatedAt": isoformat(generated_at),
            "sources": [status.to_dict() for status in statuses],
        },
    )
    latest = {
        "schemaVersion": 1,
        "canonicalFormat": "yaml",
        "generatedAt": isoformat(generated_at),
        "latestBriefingYamlUrl": relative_data_url(data_dir, b_path),
        "latestArticlesYamlUrl": relative_data_url(data_dir, a_path),
        "latestBriefingUrl": relative_data_url(data_dir, b_path.with_suffix(".json")),
        "latestArticlesUrl": relative_data_url(data_dir, a_path.with_suffix(".json")),
        "latestHourlyBriefingUrl": relative_data_url(data_dir, b_path.with_suffix(".json")) if kind == "hourly" else None,
        "latestMorningBriefingUrl": relative_data_url(data_dir, b_path.with_suffix(".json")) if kind == "morning" else None,
        "latestEveningBriefingUrl": relative_data_url(data_dir, b_path.with_suffix(".json")) if kind == "evening" else None,
        "health": {
            "ok": all(status.ok for status in statuses),
            "sourceCount": len(statuses),
            "failedSourceCount": len([status for status in statuses if not status.ok]),
        },
    }
    write_data(data_dir / "latest.yaml", latest)
    enforce_retention(data_dir, generated_at, app_config.retention_days)
    write_manifest(data_dir, generated_at, app_config.retention_days)
    return latest


def relative_data_url(data_dir: Path, path: Path) -> str:
    return path.relative_to(data_dir).as_posix()


def write_manifest(data_dir: Path, generated_at: datetime, retention_days: int) -> None:
    briefings = sorted(relative_data_url(data_dir, path) for path in (data_dir / "briefings").rglob("*.yaml"))
    articles = sorted(relative_data_url(data_dir, path) for path in (data_dir / "articles").rglob("*.yaml"))
    write_data(
        data_dir / "manifest.yaml",
        {
            "schemaVersion": 1,
            "canonicalFormat": "yaml",
            "generatedAt": isoformat(generated_at),
            "retentionDays": retention_days,
            "briefings": briefings,
            "articles": articles,
        },
    )


def enforce_retention(data_dir: Path, now: datetime, retention_days: int) -> None:
    cutoff_date = (now.astimezone(UTC) - timedelta(days=retention_days)).date()
    for root_name in ["articles", "briefings"]:
        root = data_dir / root_name
        if not root.exists():
            continue
        for path in [*root.rglob("*.yaml"), *root.rglob("*.json")]:
            path_date = date_from_data_path(root_name, path)
            if path_date is not None and path_date < cutoff_date:
                path.unlink(missing_ok=True)
    prune_empty_directories(data_dir / "articles")
    prune_empty_directories(data_dir / "briefings")


def date_from_data_path(root_name: str, path: Path) -> datetime.date | None:
    parts = path.parts
    try:
        root_index = parts.index(root_name)
        year = int(parts[root_index + 1])
        month = int(parts[root_index + 2])
        if root_name == "articles":
            day = int(Path(parts[root_index + 3]).stem)
        else:
            day = int(parts[root_index + 3])
        return datetime(year, month, day, tzinfo=UTC).date()
    except (ValueError, IndexError):
        return None


def prune_empty_directories(root: Path) -> None:
    if not root.exists():
        return
    for directory in sorted([path for path in root.rglob("*") if path.is_dir()], reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass

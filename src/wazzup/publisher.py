from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .ai import SummaryResponse, TransparencyReportResponse
from .feeds import isoformat, stable_hash
from .models import AppConfig, BriefingKind, ContentItem, ScoredItem, SourceStatus


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
    citations: list[dict[str, Any]] = []
    source_item_ids: list[str] = []
    for scored in scored_items:
        for item in scored_citation_items(scored):
            if item.id in source_item_ids:
                continue
            source_item_ids.append(item.id)
            citations.append(citation_from_item(item, scored))
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
        "sourceItemIds": source_item_ids,
        "citations": citations,
        "model": provider.get("model", "unknown"),
        "provider": provider,
        "promptVersion": provider.get("promptVersion", "summary-v1"),
        "costEstimate": provider.get("costEstimate", {"amount": 0, "currency": "USD"}),
    }


def scored_citation_items(scored: ScoredItem) -> list[ContentItem]:
    return [scored.item, *scored.item.related_items]


def citation_from_item(item: ContentItem, scored: ScoredItem) -> dict[str, Any]:
    return {
        "itemId": item.id,
        "title": item.title,
        "url": item.url,
        "sourceId": item.source_id,
        "sourceName": item.source_name,
        "sourceTag": item.source_tag,
        "tags": item.tags,
        "publishedAt": item.published_at,
        "temperature": article_temperature(scored),
    }


def article_temperature(scored: ScoredItem) -> dict[str, Any]:
    if scored.score >= 34:
        return {"level": "hot", "label": "High priority", "icon": "🔥"}
    if scored.score >= 24:
        return {"level": "warm", "label": "Worth knowing", "icon": "⚡"}
    return {"level": "cool", "label": "Background", "icon": "📄"}


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


def transparency_report_path(data_dir: Path, kind: BriefingKind, window_end: datetime) -> Path:
    year, month, day = date_parts(window_end)
    if kind == "hourly":
        filename = f"hourly-{window_end:%H}.yaml"
    else:
        filename = f"{kind}.yaml"
    return data_dir / "transparency" / year / month / day / filename


def build_transparency_report(
    kind: BriefingKind,
    window_start: datetime,
    window_end: datetime,
    generated_at: datetime,
    app_config: AppConfig,
    scored_items: list[ScoredItem],
    statuses: list[SourceStatus],
    report: TransparencyReportResponse,
) -> dict[str, Any]:
    failed_sources = [status for status in statuses if not status.ok]
    return {
        "schemaVersion": 1,
        "id": f"transparency-{kind}-{stable_hash(isoformat(window_start), isoformat(window_end), report.title)}",
        "kind": kind,
        "windowStart": isoformat(window_start),
        "windowEnd": isoformat(window_end),
        "generatedAt": isoformat(generated_at),
        "timezone": app_config.timezone,
        "language": app_config.summary_language,
        "title": report.title,
        "summary": report.summary,
        "sections": report.sections,
        "metrics": {
            "sourceCount": len(statuses),
            "failedSourceCount": len(failed_sources),
            "rawItemCount": sum(status.item_count for status in statuses),
            "selectedItemCount": len(scored_items),
            "selectedSourceItemIds": [scored.item.id for scored in scored_items],
        },
        "failedSources": [status.to_dict() for status in failed_sources],
        "provider": report.provider,
        "promptVersion": report.provider.get("promptVersion", "transparency-v1"),
    }


def markdown_transparency_report(payload: dict[str, Any]) -> str:
    lines = [f"# {payload['title']}", "", str(payload["summary"]), ""]
    metrics = payload.get("metrics", {})
    if isinstance(metrics, dict):
        lines.extend(
            [
                "## Metrics",
                "",
                f"- Sources checked: {metrics.get('sourceCount', 0)}",
                f"- Failed sources: {metrics.get('failedSourceCount', 0)}",
                f"- Raw feed items fetched: {metrics.get('rawItemCount', 0)}",
                f"- Selected items: {metrics.get('selectedItemCount', 0)}",
                "",
            ]
        )
    for section in payload.get("sections", []):
        if not isinstance(section, dict):
            continue
        title = str(section.get("title", "")).strip()
        if not title:
            continue
        lines.extend([f"## {title}", ""])
        bullets = section.get("bullets", [])
        if isinstance(bullets, list):
            for bullet in bullets:
                text = str(bullet).strip()
                if text:
                    lines.append(f"- {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_markdown(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_transparency_report(payload), encoding="utf-8")


def publish_outputs(
    public_dir: Path,
    kind: BriefingKind,
    window_start: datetime,
    window_end: datetime,
    generated_at: datetime,
    app_config: AppConfig,
    scored_items: list[ScoredItem],
    summary: SummaryResponse,
    transparency_report: TransparencyReportResponse,
    statuses: list[SourceStatus],
) -> dict[str, Any]:
    data_dir = public_dir / "data"
    public_dir.mkdir(parents=True, exist_ok=True)
    previous_latest: dict[str, Any] = {}
    latest_json_path = data_dir / "latest.json"
    if latest_json_path.exists():
        import json

        previous_latest = json.loads(latest_json_path.read_text(encoding="utf-8"))
    briefing = build_briefing(kind, window_start, window_end, generated_at, app_config, scored_items, summary)
    transparency = build_transparency_report(kind, window_start, window_end, generated_at, app_config, scored_items, statuses, transparency_report)
    b_path = briefing_path(data_dir, kind, window_end)
    a_path = articles_path(data_dir, window_end)
    t_path = transparency_report_path(data_dir, kind, window_end)
    write_data(b_path, briefing)
    write_data(
        a_path,
        {
            "schemaVersion": 1,
            "generatedAt": isoformat(generated_at),
            "items": [scored.to_dict() for scored in scored_items],
        },
    )
    write_data(t_path, transparency)
    write_markdown(t_path.with_suffix(".md"), transparency)
    write_markdown(data_dir / "transparency" / "latest.md", transparency)
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
        "latestBriefingYamlUrl": public_data_url(data_dir, b_path),
        "latestArticlesYamlUrl": public_data_url(data_dir, a_path),
        "latestTransparencyReportYamlUrl": public_data_url(data_dir, t_path),
        "latestBriefingUrl": public_data_url(data_dir, b_path.with_suffix(".json")),
        "latestArticlesUrl": public_data_url(data_dir, a_path.with_suffix(".json")),
        "latestTransparencyReportUrl": public_data_url(data_dir, t_path.with_suffix(".json")),
        "latestTransparencyReportMarkdownUrl": public_data_url(data_dir, t_path.with_suffix(".md")),
        "latestHourlyBriefingUrl": (
            public_data_url(data_dir, b_path.with_suffix(".json"))
            if kind == "hourly"
            else previous_latest.get("latestHourlyBriefingUrl")
        ),
        "latestMorningBriefingUrl": (
            public_data_url(data_dir, b_path.with_suffix(".json"))
            if kind == "morning"
            else previous_latest.get("latestMorningBriefingUrl")
        ),
        "latestEveningBriefingUrl": (
            public_data_url(data_dir, b_path.with_suffix(".json"))
            if kind == "evening"
            else previous_latest.get("latestEveningBriefingUrl")
        ),
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


def public_data_url(data_dir: Path, path: Path) -> str:
    return f"data/{relative_data_url(data_dir, path)}"


def write_manifest(data_dir: Path, generated_at: datetime, retention_days: int) -> None:
    briefings = sorted(relative_data_url(data_dir, path) for path in (data_dir / "briefings").rglob("*.yaml"))
    articles = sorted(relative_data_url(data_dir, path) for path in (data_dir / "articles").rglob("*.yaml"))
    transparency_reports = sorted(relative_data_url(data_dir, path) for path in (data_dir / "transparency").rglob("*.yaml"))
    write_data(
        data_dir / "manifest.yaml",
        {
            "schemaVersion": 1,
            "canonicalFormat": "yaml",
            "generatedAt": isoformat(generated_at),
            "retentionDays": retention_days,
            "briefings": briefings,
            "articles": articles,
            "transparencyReports": transparency_reports,
        },
    )


def enforce_retention(data_dir: Path, now: datetime, retention_days: int) -> None:
    cutoff_date = (now.astimezone(UTC) - timedelta(days=retention_days)).date()
    for root_name in ["articles", "briefings", "transparency"]:
        root = data_dir / root_name
        if not root.exists():
            continue
        for path in [*root.rglob("*.yaml"), *root.rglob("*.json"), *root.rglob("*.md")]:
            path_date = date_from_data_path(root_name, path)
            if path_date is not None and path_date < cutoff_date:
                path.unlink(missing_ok=True)
    prune_empty_directories(data_dir / "articles")
    prune_empty_directories(data_dir / "briefings")
    prune_empty_directories(data_dir / "transparency")


def date_from_data_path(root_name: str, path: Path) -> datetime.date | None:
    parts = path.parts
    try:
        root_index = parts.index(root_name)
        year = int(parts[root_index + 1])
        month = int(parts[root_index + 2])
        if root_name == "articles":
            day = int(Path(parts[root_index + 3]).stem)
        elif root_name in {"briefings", "transparency"}:
            day = int(parts[root_index + 3])
        else:
            return None
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

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence


class ValidationError(ValueError):
    """Raised when generated static data is invalid."""


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValidationError(f"Missing required JSON file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValidationError(f"Expected object in {path}")
    return payload


def require_keys(payload: dict[str, Any], keys: list[str], name: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise ValidationError(f"{name} missing keys: {', '.join(missing)}")


def validate_briefing(path: Path) -> None:
    payload = load_json(path)
    require_keys(
        payload,
        [
            "schemaVersion",
            "id",
            "kind",
            "windowStart",
            "windowEnd",
            "generatedAt",
            "timezone",
            "language",
            "headline",
            "sections",
            "sourceItemIds",
            "citations",
            "provider",
            "promptVersion",
        ],
        str(path),
    )
    if payload["language"] != "en":
        raise ValidationError(f"Briefing must be English: {path}")
    if not isinstance(payload["sections"], list) or not payload["sections"]:
        raise ValidationError(f"Briefing has no sections: {path}")
    valid_item_ids = set(payload.get("sourceItemIds", []))
    for section in payload["sections"]:
        bullets = section.get("bullets") if isinstance(section, dict) else None
        if not isinstance(bullets, list):
            raise ValidationError(f"Briefing section has no bullets: {path}")
        for bullet in bullets:
            citations = bullet.get("citations") if isinstance(bullet, dict) else None
            if citations and not set(citations).issubset(valid_item_ids):
                raise ValidationError(f"Briefing citation references unknown item: {path}")


def validate_articles(path: Path) -> None:
    payload = load_json(path)
    require_keys(payload, ["schemaVersion", "generatedAt", "items"], str(path))
    if not isinstance(payload["items"], list):
        raise ValidationError(f"Articles items must be a list: {path}")
    required = {"id", "sourceId", "title", "url", "canonicalUrl", "publishedAt", "score"}
    for item in payload["items"]:
        if not isinstance(item, dict) or not required.issubset(item):
            raise ValidationError(f"Invalid article record in {path}")


def validate_data_dir(data_dir: Path) -> None:
    latest = load_json(data_dir / "latest.json")
    require_keys(latest, ["schemaVersion", "generatedAt", "latestBriefingUrl", "latestArticlesUrl", "health"], "latest.json")
    briefing_path = data_dir / latest["latestBriefingUrl"]
    articles_path = data_dir / latest["latestArticlesUrl"]
    validate_briefing(briefing_path)
    validate_articles(articles_path)
    load_json(data_dir / "sources" / "status.json")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate generated Wazzup static JSON data")
    parser.add_argument("data_dir", nargs="?", default="public/data")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    validate_data_dir(Path(args.data_dir))
    print(f"validated {args.data_dir}")


if __name__ == "__main__":
    main()

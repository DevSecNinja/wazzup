from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import AppConfig, Interest, SourceConfig

DEFAULT_HEADERS = {
    "User-Agent": "Wazzup/0.1 (+https://github.com/DevSecNinja/wazzup)",
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
}


class ConfigError(ValueError):
    """Raised when a configuration file is invalid."""


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing configuration file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ConfigError(f"Configuration must be a mapping: {path}")
    return payload


def _require_str(source: dict[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Missing or invalid string field: {key}")
    return value.strip()


def _str_list(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"Expected list of strings for {key}")
    return [item.strip() for item in value if item.strip()]


def load_sources(path: str | Path = "config/sources.yml") -> list[SourceConfig]:
    payload = _read_yaml(Path(path))
    defaults = payload.get("defaults", {})
    default_headers = dict(DEFAULT_HEADERS)
    default_headers.update(defaults.get("fetch", {}).get("headers", {}) or {})
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ConfigError("sources.yml must contain a non-empty sources list")

    sources: list[SourceConfig] = []
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            raise ConfigError("Every source must be a mapping")
        fetch_headers = raw_source.get("fetch", {}).get("headers", {}) or {}
        if not isinstance(fetch_headers, dict):
            raise ConfigError(f"Invalid fetch.headers for {raw_source.get('id', '<unknown>')}")
        headers = {str(key): str(value) for key, value in default_headers.items()}
        headers.update({str(key): str(value) for key, value in fetch_headers.items()})
        source_type = _require_str(raw_source, "type")
        if source_type not in {"rss", "atom", "json-feed", "podcast"}:
            raise ConfigError(f"Unsupported source type: {source_type}")
        sources.append(
            SourceConfig(
                id=_require_str(raw_source, "id"),
                name=_require_str(raw_source, "name"),
                type=source_type,  # type: ignore[arg-type]
                homepage_url=_require_str(raw_source, "homepageUrl"),
                feed_url=_require_str(raw_source, "feedUrl"),
                language=_require_str(raw_source, "language"),
                region=_require_str(raw_source, "region"),
                weight=float(raw_source.get("weight", 1.0)),
                categories=_str_list(raw_source.get("categories"), "categories"),
                interest_hints=_str_list(raw_source.get("interestHints"), "interestHints"),
                enabled=bool(raw_source.get("enabled", True)),
                headers=headers,
                notes=raw_source.get("notes") if isinstance(raw_source.get("notes"), str) else None,
            )
        )
    return sources


def load_app_config(path: str | Path = "config/interests.yml") -> AppConfig:
    payload = _read_yaml(Path(path))
    raw_interests = payload.get("interests")
    if not isinstance(raw_interests, list) or not raw_interests:
        raise ConfigError("interests.yml must contain a non-empty interests list")
    interests: list[Interest] = []
    for raw_interest in raw_interests:
        if not isinstance(raw_interest, dict):
            raise ConfigError("Every interest must be a mapping")
        interests.append(
            Interest(
                id=_require_str(raw_interest, "id"),
                name=_require_str(raw_interest, "name"),
                weight=float(raw_interest.get("weight", 1.0)),
                keywords=_str_list(raw_interest.get("keywords"), "keywords"),
            )
        )
    briefings = payload.get("briefings", {}) or {}
    return AppConfig(
        summary_language=str(payload.get("summaryLanguage", "en")),
        retention_days=int(payload.get("retentionDays", 35)),
        timezone=str(payload.get("timezone", "Europe/Amsterdam")),
        morning_local_time=str(briefings.get("morningLocalTime", "07:00")),
        evening_local_time=str(briefings.get("eveningLocalTime", "20:00")),
        interests=interests,
    )

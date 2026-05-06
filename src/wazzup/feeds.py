from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from .models import ContentItem, SourceConfig, SourceStatus

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}

TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def isoformat(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: str | None, *, max_length: int | None = None) -> str:
    if not value:
        return ""
    text = html.unescape(value)
    text = TAG_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    if max_length and len(text) > max_length:
        return text[: max_length - 1].rstrip() + "…"
    return text


def canonicalize_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [(key, value) for key, value in query if key.lower() not in TRACKING_PARAMS]
    normalized_query = urllib.parse.urlencode(filtered, doseq=True)
    path = parsed.path or "/"
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, normalized_query, ""))


def stable_hash(*parts: str, length: int = 16) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:length]


def parse_date(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    raw = value.strip()
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    try:
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return fallback


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(element: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in list(element):
        if local_name(child.tag) in wanted:
            return "".join(child.itertext()).strip()
    return ""


def children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(element) if local_name(child.tag) == name.lower()]


def atom_link(element: ET.Element) -> str:
    for child in children(element, "link"):
        rel = child.attrib.get("rel", "alternate")
        href = child.attrib.get("href")
        if href and rel in {"alternate", ""}:
            return href
    return child_text(element, "link")


def fetch_feed(source: SourceConfig, timeout_seconds: int = 30) -> bytes:
    request = urllib.request.Request(source.feed_url, headers=source.headers)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def parse_feed(source: SourceConfig, payload: bytes, discovered_at: datetime | None = None) -> list[ContentItem]:
    discovered = discovered_at or utc_now()
    root = ET.fromstring(payload)
    root_name = local_name(root.tag)
    if root_name == "rss":
        channel = next((child for child in list(root) if local_name(child.tag) == "channel"), root)
        entries = children(channel, "item")
    elif root_name == "feed":
        entries = children(root, "entry")
    else:
        raise ValueError(f"Unsupported feed root: {root.tag}")

    items: list[ContentItem] = []
    for index, entry in enumerate(entries):
        title = clean_text(child_text(entry, "title"), max_length=300)
        if root_name == "feed":
            url = atom_link(entry)
            raw_date = child_text(entry, "updated", "published")
            summary = child_text(entry, "summary", "content")
            author = child_text(entry, "author")
        else:
            url = child_text(entry, "link")
            raw_date = child_text(entry, "pubDate", "date", "updated")
            summary = child_text(entry, "description", "encoded", "summary")
            author = child_text(entry, "creator", "author")
        guid = child_text(entry, "guid", "id") or url or f"{source.id}:{index}"
        if not title or not url:
            continue
        canonical_url = canonicalize_url(url)
        published = parse_date(raw_date, discovered)
        clean_summary = clean_text(summary, max_length=500)
        tags = [clean_text(category) for category in [child.text or "" for child in children(entry, "category")]]
        tags = [tag for tag in tags if tag]
        content_hash = stable_hash(title, canonical_url, clean_summary, isoformat(published), length=32)
        item_id = f"item-{stable_hash(source.id, canonical_url or guid, isoformat(published))}"
        raw_ref = guid.strip() if guid else canonical_url
        items.append(
            ContentItem(
                schema_version=1,
                id=item_id,
                source_id=source.id,
                source_name=source.name,
                source_type=source.type,
                title=title,
                url=url.strip(),
                canonical_url=canonical_url,
                published_at=isoformat(published),
                discovered_at=isoformat(discovered),
                authors=[clean_text(author)] if clean_text(author) else [],
                tags=tags + source.categories,
                language=source.language,
                summary=clean_summary,
                content_hash=content_hash,
                raw_ref=raw_ref,
            )
        )
    return items


def fetch_and_parse(source: SourceConfig, discovered_at: datetime | None = None) -> tuple[list[ContentItem], SourceStatus]:
    fetched_at = discovered_at or utc_now()
    try:
        payload = fetch_feed(source)
        items = parse_feed(source, payload, fetched_at)
        return items, SourceStatus(source.id, True, isoformat(fetched_at), len(items), "ok")
    except Exception as exc:  # noqa: BLE001 - keep per-source failures isolated
        return [], SourceStatus(source.id, False, isoformat(fetched_at), 0, f"{type(exc).__name__}: {exc}")


def deduplicate(items: list[ContentItem]) -> list[ContentItem]:
    by_key: dict[str, ContentItem] = {}
    for item in items:
        key = item.canonical_url or item.raw_ref
        existing = by_key.get(key)
        if existing is None or item.source_id.startswith("microsoft-security-threat-intelligence"):
            by_key[key] = item
    return list(by_key.values())

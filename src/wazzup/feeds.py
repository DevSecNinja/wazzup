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
NON_WORD_RE = re.compile(r"[^\w\s-]", re.UNICODE)


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


def merge_tags(*tag_groups: list[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for group in tag_groups:
        for tag in group:
            clean = clean_text(tag, max_length=40)
            key = clean.lower()
            if clean and key not in seen:
                tags.append(clean)
                seen.add(key)
    return tags


def normalize_title(value: str) -> str:
    text = clean_text(value).lower()
    text = NON_WORD_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    prefixes = ["breaking ", "update ", "exclusive "]
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text


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
        feed_tags = [child.text or "" for child in children(entry, "category")]
        tags = merge_tags([source.source_tag], source.categories, feed_tags)
        content_hash = stable_hash(title, canonical_url, clean_summary, isoformat(published), length=32)
        item_id = f"item-{stable_hash(source.id, canonical_url or guid, isoformat(published))}"
        raw_ref = guid.strip() if guid else canonical_url
        items.append(
            ContentItem(
                schema_version=1,
                id=item_id,
                source_id=source.id,
                source_name=source.name,
                source_tag=source.source_tag,
                source_type=source.type,
                title=title,
                url=url.strip(),
                canonical_url=canonical_url,
                published_at=isoformat(published),
                discovered_at=isoformat(discovered),
                authors=[clean_text(author)] if clean_text(author) else [],
                tags=tags,
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
        last_article_at = max((item.published_at for item in items), default=None)
        return items, SourceStatus(source.id, True, isoformat(fetched_at), len(items), "ok", last_article_at)
    except Exception as exc:  # noqa: BLE001 - keep per-source failures isolated
        return [], SourceStatus(source.id, False, isoformat(fetched_at), 0, f"{type(exc).__name__}: {exc}")


def deduplication_keys(item: ContentItem) -> list[str]:
    published_day = item.published_at[:10]
    keys = []
    if item.canonical_url:
        keys.append(f"url:{item.canonical_url}")
    if item.raw_ref and item.raw_ref != item.canonical_url:
        keys.append(f"ref:{item.raw_ref}")
    normalized_title = normalize_title(item.title)
    if len(normalized_title) >= 18:
        keys.append(f"title-day:{published_day}:{normalized_title}")
    return keys or [f"id:{item.id}"]


def item_priority(item: ContentItem) -> tuple[int, int, str]:
    source_priority = 2 if item.source_id == "microsoft-security-threat-intelligence" else 1
    return source_priority, len(item.summary), item.published_at


def deduplicate(items: list[ContentItem]) -> list[ContentItem]:
    groups: list[tuple[set[str], list[ContentItem]]] = []
    for item in items:
        keys = set(deduplication_keys(item))
        matching_indexes = [index for index, (group_keys, _) in enumerate(groups) if group_keys & keys]
        if not matching_indexes:
            groups.append((keys, [item]))
            continue
        first_index = matching_indexes[0]
        groups[first_index][0].update(keys)
        groups[first_index][1].append(item)
        for index in reversed(matching_indexes[1:]):
            groups[first_index][0].update(groups[index][0])
            groups[first_index][1].extend(groups[index][1])
            del groups[index]

    winners = [max(group_items, key=item_priority) for _, group_items in groups]
    return sorted(winners, key=lambda item: item.published_at, reverse=True)

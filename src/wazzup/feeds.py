from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import UTC, datetime, timedelta
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
MIN_STORY_SHARED_KEYWORDS = 2
MAX_STORY_TIME_DELTA = timedelta(hours=18)
STORY_STOPWORDS = {
    "about",
    "after",
    "analysis",
    "announces",
    "attack",
    "attacks",
    "breaking",
    "commentary",
    "cyber",
    "for",
    "from",
    "incident",
    "inside",
    "latest",
    "new",
    "news",
    "report",
    "reports",
    "security",
    "story",
    "the",
    "threat",
    "update",
}


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


def fetch_feed(source: SourceConfig, timeout_seconds: int | None = None) -> bytes:
    timeout = timeout_seconds if timeout_seconds is not None else source.timeout_seconds
    request = urllib.request.Request(source.feed_url, headers=source.headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
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

    winners = []
    for _, group_items in groups:
        winner = max(group_items, key=item_priority)
        related_items = tuple(
            sorted(
                [replace(item, related_items=()) for item in group_items if item.id != winner.id],
                key=item_priority,
                reverse=True,
            )
        )
        winners.append(replace(winner, related_items=related_items) if related_items else winner)
    return sorted(winners, key=lambda item: item.published_at, reverse=True)


def _keyword_tokens(value: str) -> set[str]:
    text = NON_WORD_RE.sub(" ", clean_text(value).lower())
    text = WHITESPACE_RE.sub(" ", text).strip()
    return {
        token
        for token in text.split(" ")
        if token and (len(token) >= 4 or any(char.isdigit() for char in token)) and token not in STORY_STOPWORDS
    }


def _story_keywords(item: ContentItem) -> set[str]:
    return _keyword_tokens(item.title) | _keyword_tokens(item.summary) | _keyword_tokens(" ".join(item.tags))


def _canonical_path_tokens(item: ContentItem) -> set[str]:
    parsed = urllib.parse.urlsplit(item.canonical_url)
    return {token for token in parsed.path.lower().split("/") if token and token != "index"}


def _story_anchor_tokens(tokens: set[str]) -> set[str]:
    return {
        token
        for token in tokens
        if any(char.isdigit() for char in token) or token.startswith(("cve", "apt", "kb")) or len(token) >= 8
    }


def _parse_content_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _story_related(left: ContentItem, right: ContentItem) -> bool:
    if abs(_parse_content_timestamp(left.published_at) - _parse_content_timestamp(right.published_at)) > MAX_STORY_TIME_DELTA:
        return False
    left_title = normalize_title(left.title)
    right_title = normalize_title(right.title)
    if left_title and left_title == right_title:
        return True
    left_keywords = _story_keywords(left)
    right_keywords = _story_keywords(right)
    if not left_keywords or not right_keywords:
        return False
    shared_keywords = left_keywords & right_keywords
    if len(shared_keywords) < MIN_STORY_SHARED_KEYWORDS:
        return False
    if not (_story_anchor_tokens(shared_keywords) | (_canonical_path_tokens(left) & _canonical_path_tokens(right))):
        return False
    overlap = len(shared_keywords) / max(1, min(len(left_keywords), len(right_keywords)))
    return overlap >= 0.5


def _flatten_group_items(item: ContentItem) -> list[ContentItem]:
    return [replace(item, related_items=()), *(replace(related, related_items=()) for related in item.related_items)]


def cluster_related_stories(items: list[ContentItem]) -> list[ContentItem]:
    groups: list[list[ContentItem]] = []
    for item in items:
        matching_indexes = [
            index for index, group_items in enumerate(groups) if any(_story_related(item, candidate) for candidate in group_items)
        ]
        if not matching_indexes:
            groups.append([item])
            continue
        first_index = matching_indexes[0]
        groups[first_index].append(item)
        for index in reversed(matching_indexes[1:]):
            groups[first_index].extend(groups[index])
            del groups[index]

    winners: list[ContentItem] = []
    for group_items in groups:
        expanded = [entry for grouped in group_items for entry in _flatten_group_items(grouped)]
        deduped_by_id: dict[str, ContentItem] = {item.id: item for item in expanded}
        flattened = list(deduped_by_id.values())
        winner = max(flattened, key=item_priority)
        related_items = tuple(
            sorted(
                (replace(item, related_items=()) for item in flattened if item.id != winner.id),
                key=item_priority,
                reverse=True,
            )
        )
        winners.append(replace(winner, related_items=related_items) if related_items else winner)
    return sorted(winners, key=lambda item: item.published_at, reverse=True)

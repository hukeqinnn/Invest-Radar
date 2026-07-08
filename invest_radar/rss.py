from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

from .html_text import clean_html_to_text, clean_text


CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}"
ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


@dataclass(frozen=True)
class FeedItem:
    source_title: str
    guid: str
    title: str
    link: str
    published_at: str
    audio_url: str
    audio_type: str
    duration: str
    image_url: str
    rss_text: str
    raw_description: str


def _child_text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _namespaced_text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _parse_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def parse_rss(xml_text: str, max_items: int | None = None) -> list[FeedItem]:
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("RSS channel not found")

    source_title = _child_text(channel, "title")
    items: list[FeedItem] = []

    for item in channel.findall("item"):
        title = clean_text(_child_text(item, "title"))
        link = _child_text(item, "link")
        guid = _child_text(item, "guid") or link or title
        pub_date = _parse_datetime(_child_text(item, "pubDate"))

        description = _child_text(item, "description")
        encoded = _namespaced_text(item, f"{CONTENT_NS}encoded")
        raw_description = encoded or description
        rss_text = clean_html_to_text(raw_description)

        enclosure = item.find("enclosure")
        audio_url = ""
        audio_type = ""
        if enclosure is not None:
            audio_url = enclosure.attrib.get("url", "")
            audio_type = enclosure.attrib.get("type", "")

        duration = _namespaced_text(item, f"{ITUNES_NS}duration")

        image = item.find(f"{ITUNES_NS}image")
        image_url = image.attrib.get("href", "") if image is not None else ""

        items.append(
            FeedItem(
                source_title=source_title,
                guid=guid,
                title=title,
                link=link,
                published_at=pub_date,
                audio_url=audio_url,
                audio_type=audio_type,
                duration=duration,
                image_url=image_url,
                rss_text=rss_text,
                raw_description=raw_description,
            )
        )
        if max_items and len(items) >= max_items:
            break

    return items


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

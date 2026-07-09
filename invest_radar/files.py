from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo


def slugify(value: str, fallback: str = "item") -> str:
    value = value.strip()
    value = re.sub(r"[\\/:*?\"<>|#%&{}$!@`'=+]", "-", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-._ ")
    return value[:90] or fallback


def _now_prefix(local_timezone: str) -> str:
    if local_timezone:
        try:
            return datetime.now(ZoneInfo(local_timezone)).strftime("%Y-%m-%d")
        except Exception:
            pass
    return datetime.now().strftime("%Y-%m-%d")


def date_prefix(value: str, local_timezone: str = "") -> str:
    if not value:
        return _now_prefix(local_timezone)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return _now_prefix(local_timezone)
    if local_timezone:
        try:
            parsed = parsed.astimezone(ZoneInfo(local_timezone))
        except Exception:
            pass
    return parsed.strftime("%Y-%m-%d")


def write_item_markdown(texts_dir: Path, row: sqlite3.Row, local_timezone: str = "") -> Path:
    source_dir = texts_dir / slugify(row["source_name"], "source")
    source_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{date_prefix(row['published_at'], local_timezone)}-{slugify(row['title'], str(row['id']))}.md"
    path = source_dir / filename

    lines = [
        f"# {row['title']}",
        "",
        f"- 来源: {row['source_name']}",
        f"- 发布时间: {row['published_at'] or '未知'}",
        f"- 原文链接: {row['link'] or '无'}",
    ]
    if row["audio_url"]:
        lines.append(f"- 音频链接: {row['audio_url']}")
    if row["duration"]:
        lines.append(f"- 时长: {row['duration']}")
    lines.extend(["", "## 正文", "", row["text"] or ""])

    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import sqlite3


def slugify(value: str, fallback: str = "item") -> str:
    value = value.strip()
    value = re.sub(r"[\\/:*?\"<>|#%&{}$!@`'=+]", "-", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-._ ")
    return value[:90] or fallback


def date_prefix(value: str) -> str:
    if not value:
        return datetime.now().strftime("%Y-%m-%d")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return datetime.now().strftime("%Y-%m-%d")


def write_item_markdown(texts_dir: Path, row: sqlite3.Row) -> Path:
    source_dir = texts_dir / slugify(row["source_name"], "source")
    source_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{date_prefix(row['published_at'])}-{slugify(row['title'], str(row['id']))}.md"
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

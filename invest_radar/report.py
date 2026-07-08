from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from .files import slugify


def _line(value: str | None) -> str:
    return value if value else "未知"


def _format_published_at(value: str | None, local_timezone: str) -> str:
    if not value:
        return "未知"
    try:
        published = datetime.fromisoformat(value)
    except ValueError:
        return value
    if not local_timezone:
        return value
    try:
        zone = ZoneInfo(local_timezone)
    except Exception:
        return value
    local = published.astimezone(zone)
    return f"{local.strftime('%Y-%m-%d %H:%M:%S')} {local_timezone} (UTC: {value})"


def _report_label(items: list[sqlite3.Row], errors: list[str] | None) -> str:
    if len(items) == 1:
        row = items[0]
        source = _line(row["source_name"])
        return f"{source}-{row['title']}"

    if len(items) > 1:
        sources = []
        for row in items:
            source = _line(row["source_name"])
            if source not in sources:
                sources.append(source)
        source_label = "-".join(sources[:3])
        if len(sources) > 3:
            source_label = f"{source_label}-等"
        return f"{len(items)}篇-{source_label}"

    if errors:
        return "抓取错误"
    return "无新增内容"


def write_report(
    reports_dir: Path,
    items: list[sqlite3.Row],
    errors: list[str] | None = None,
    *,
    local_timezone: str = "",
) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    report_label = _report_label(items, errors)
    report_slug = slugify(report_label, "report")
    path = reports_dir / f"daily-{now.strftime('%Y-%m-%d-%H%M%S')}-{report_slug}.md"

    lines = [
        f"# 每日抓取报告 {now.strftime('%Y-%m-%d')} - {report_label}",
        "",
        f"生成时间: {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"报告主题: {report_label}",
        "",
        "> 本报告是信息整理，不构成投资建议。",
        "",
    ]

    if errors:
        lines.append("## 抓取错误")
        lines.extend(f"- {error}" for error in errors)
        lines.append("")

    lines.append(f"## 本次处理内容（{len(items)}）")
    lines.append("")

    if not items:
        lines.append("今天没有发现新增内容，也没有生成新的逐字稿。")
    else:
        for row in items:
            title = row["title"]
            link = row["link"]
            heading = f"### [{title}]({link})" if link else f"### {title}"
            lines.extend(
                [
                    heading,
                    "",
                    f"- 来源: {_line(row['source_name'])}",
                    f"- 发布时间: {_format_published_at(row['published_at'], local_timezone)}",
                    f"- 本地正文: `{_line(row['text_path'])}`",
                ]
            )
            if "transcript_path" in row.keys() and row["transcript_path"]:
                lines.append(f"- 本地逐字稿: `{row['transcript_path']}`")
            if "summary_path" in row.keys() and row["summary_path"]:
                lines.append(f"- 系统摘要: `{row['summary_path']}`")
            if "summary_kind" in row.keys() and row["summary_kind"]:
                model = f" / {row['summary_model']}" if row["summary_model"] else ""
                lines.append(f"- 摘要方式: {row['summary_kind']}{model}")
            if row["duration"]:
                lines.append(f"- 时长: {row['duration']}")
            if row["audio_url"]:
                lines.append(f"- 音频: {row['audio_url']}")
            lines.extend(["", row["summary"] or "暂无摘要。", ""])

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from .audio import (
    audio_path_for_item,
    delete_audio_artifacts,
    download_audio,
    transcribe_audio,
    transcript_path_for_item,
    write_transcript_markdown,
)
from .config import AppConfig, Source
from .fetcher import fetch_text
from .files import write_item_markdown
from .html_text import clean_html_to_text
from .llm_summary import (
    LLMConfig,
    summarize_with_llm,
    summary_path_for_item,
    write_summary_markdown,
)
from .report import write_report
from .rss import FeedItem, parse_rss
from .store import (
    connect,
    get_item,
    get_state,
    init_db,
    items_needing_llm_summary,
    items_needing_llm_summary_by_ids,
    items_needing_transcript,
    items_needing_transcript_by_ids,
    items_without_summary,
    items_without_summary_by_ids,
    set_state,
    update_audio_path,
    update_summary,
    update_text_path,
    update_transcript,
    upsert_item,
)
from .summary import summarize_text


LAST_SUCCESSFUL_SCAN_KEY = "last_successful_scan_at"
SOURCE_SUCCESSFUL_SCAN_PREFIX = "last_successful_scan_at:source:"


@dataclass(frozen=True)
class RunResult:
    new_count: int
    transcribed_count: int
    llm_summarized_count: int
    summarized_count: int
    report_path: Path
    errors: tuple[str, ...]


@dataclass(frozen=True)
class LLMSummaryResult:
    summarized_count: int
    summary_paths: tuple[Path, ...]
    errors: tuple[str, ...]


def _item_text_from_feed(item: FeedItem, source: Source, config: AppConfig) -> str:
    text = item.rss_text
    should_fetch_page = (
        source.fetch_full_pages
        if source.fetch_full_pages is not None
        else config.settings.fetch_full_pages
    )
    if should_fetch_page and item.link:
        page = fetch_text(item.link)
        page_text = clean_html_to_text(page.body)
        if len(page_text) > len(text) * 1.3:
            text = page_text
    return text


def _local_zone(config: AppConfig) -> ZoneInfo | None:
    if not config.settings.local_timezone:
        return None
    try:
        return ZoneInfo(config.settings.local_timezone)
    except Exception:
        return None


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_published_today(published_at: str, zone: ZoneInfo | None) -> bool:
    published = _parse_iso_datetime(published_at)
    if published is None:
        return False
    if zone is not None:
        published_date = published.astimezone(zone).date()
        today = datetime.now(zone).date()
    else:
        published_date = published.astimezone().date()
        today = datetime.now().astimezone().date()
    return published_date == today


def _is_published_in_window(published_at: str, window_start: datetime, window_end: datetime) -> bool:
    published = _parse_iso_datetime(published_at)
    if published is None:
        return False
    return window_start <= published <= window_end


def _fallback_scan_window_start(scan_started_at: datetime, zone: ZoneInfo | None) -> datetime:
    local_now = scan_started_at.astimezone(zone) if zone is not None else scan_started_at.astimezone()
    local_time = local_now.time()
    if local_time >= time(18, 0):
        local_start = local_now.replace(hour=10, minute=30, second=0, microsecond=0)
    elif local_time >= time(10, 30):
        yesterday = local_now - timedelta(days=1)
        local_start = yesterday.replace(hour=18, minute=0, second=0, microsecond=0)
    else:
        yesterday = local_now - timedelta(days=1)
        local_start = yesterday.replace(hour=18, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc)


def _source_state_key(source: Source) -> str:
    return f"{SOURCE_SUCCESSFUL_SCAN_PREFIX}{source.url}"


def _scan_window_for_source(
    conn: sqlite3.Connection,
    config: AppConfig,
    source: Source,
    zone: ZoneInfo | None,
    scan_started_at: datetime,
) -> tuple[datetime, datetime] | None:
    if not config.settings.scan_since_last_run:
        return None

    saved_start = _parse_iso_datetime(get_state(conn, _source_state_key(source)))
    if saved_start is None:
        saved_start = _parse_iso_datetime(get_state(conn, LAST_SUCCESSFUL_SCAN_KEY))
    window_start = saved_start or _fallback_scan_window_start(scan_started_at, zone)
    return window_start, scan_started_at


def _source_url_for_error(config: AppConfig, error: str) -> str:
    for source in config.sources:
        if error.startswith(f"{source.name}:") or error.startswith(f"{source.name} /"):
            return source.url
    return ""


def _source_for_row(config: AppConfig, row: sqlite3.Row) -> Source | None:
    source_url = row["source_url"] if "source_url" in row.keys() else ""
    for source in config.sources:
        if source.url == source_url:
            return source
    return None


def _source_bool(value: bool | None, default: bool) -> bool:
    return default if value is None else bool(value)


def _process_source(
    conn: sqlite3.Connection,
    config: AppConfig,
    source: Source,
    zone: ZoneInfo | None,
    scan_window: tuple[datetime, datetime] | None,
) -> tuple[list[int], list[int], list[str]]:
    errors: list[str] = []
    candidate_ids: list[int] = []
    new_ids: list[int] = []

    if source.type != "rss":
        return [], [], [f"{source.name}: unsupported source type {source.type}"]

    try:
        feed = fetch_text(source.url)
        items = parse_rss(feed.body, max_items=config.settings.max_items_per_source)
    except Exception as exc:  # noqa: BLE001 - keep one source from stopping the run.
        return [], [], [f"{source.name}: {exc}"]

    for item in items:
        if scan_window is not None:
            if not _is_published_in_window(item.published_at, scan_window[0], scan_window[1]):
                continue
        elif config.settings.only_today and not _is_published_today(item.published_at, zone):
            continue
        try:
            text = _item_text_from_feed(item, source, config)
            stored = upsert_item(
                conn,
                source_name=source.name or item.source_title,
                source_url=source.url,
                guid=item.guid,
                title=item.title,
                link=item.link,
                published_at=item.published_at,
                audio_url=item.audio_url,
                audio_type=item.audio_type,
                duration=item.duration,
                image_url=item.image_url,
                raw_text=item.raw_description,
                text=text,
            )
            row = get_item(conn, stored.id)
            text_path = write_item_markdown(
                config.settings.texts_dir,
                row,
                local_timezone=config.settings.local_timezone,
            )
            update_text_path(conn, stored.id, text_path)
            candidate_ids.append(stored.id)
            if stored.is_new:
                new_ids.append(stored.id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{source.name} / {item.title}: {exc}")

    return candidate_ids, new_ids, errors


def summarize_pending(conn: sqlite3.Connection, config: AppConfig, candidate_ids: list[int] | None = None) -> int:
    count = 0
    rows = items_without_summary_by_ids(conn, candidate_ids) if candidate_ids is not None else items_without_summary(conn)
    for row in rows:
        summary = summarize_text(
            row["transcript"] or row["text"] or "",
            sentence_count=config.settings.summary_sentences,
            keywords=config.settings.keywords,
        )
        update_summary(conn, int(row["id"]), summary)
        count += 1
    return count


def llm_config_from_app(config: AppConfig) -> LLMConfig:
    return LLMConfig(
        base_url=config.settings.llm_base_url,
        model=config.settings.llm_model,
        api_key_env=config.settings.llm_api_key_env,
        keychain_service=config.settings.llm_keychain_service,
        keychain_account=config.settings.llm_keychain_account,
        reasoning_effort=config.settings.llm_reasoning_effort,
        verbosity=config.settings.llm_verbosity,
        timeout_seconds=config.settings.llm_timeout_seconds,
        max_chars_per_chunk=config.settings.llm_max_chars_per_chunk,
    )


def _summarize_rows_with_llm(
    conn: sqlite3.Connection,
    config: AppConfig,
    rows: list[sqlite3.Row],
) -> tuple[list[int], list[str]]:
    llm_config = llm_config_from_app(config)
    summarized_ids: list[int] = []
    errors: list[str] = []

    for row in rows:
        try:
            summary = summarize_with_llm(
                title=row["title"],
                source=row["source_name"],
                transcript=row["transcript"] or row["text"] or "",
                config=llm_config,
            )
            summary_path = summary_path_for_item(
                config.settings.summaries_dir,
                row["source_name"],
                row["title"],
                row["published_at"] or "",
                config.settings.local_timezone,
            )
            write_summary_markdown(
                summary_path,
                title=row["title"],
                source_name=row["source_name"],
                published_at=row["published_at"] or "",
                link=row["link"] or "",
                model=config.settings.llm_model,
                summary=summary,
            )
            update_summary(
                conn,
                int(row["id"]),
                summary,
                kind="llm",
                model=config.settings.llm_model,
                summary_path=summary_path,
            )
            summarized_ids.append(int(row["id"]))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{row['source_name']} / {row['title']}: LLM summary failed: {exc}")

    return summarized_ids, errors


def summarize_pending_with_llm(
    conn: sqlite3.Connection,
    config: AppConfig,
    candidate_ids: list[int],
) -> tuple[list[int], list[str]]:
    if config.settings.summary_mode != "llm":
        return [], []
    if not candidate_ids:
        return [], []

    rows = items_needing_llm_summary_by_ids(conn, candidate_ids, config.settings.max_llm_summaries_per_run)
    return _summarize_rows_with_llm(conn, config, rows)


def summarize_existing_with_llm(config: AppConfig, limit: int = 1) -> LLMSummaryResult:
    config.settings.summaries_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(config.settings.database)
    init_db(conn)
    rows = items_needing_llm_summary(conn, limit)
    summarized_ids, errors = _summarize_rows_with_llm(conn, config, rows)
    summary_paths: list[Path] = []
    for item_id in summarized_ids:
        row = get_item(conn, item_id)
        if row["summary_path"]:
            summary_paths.append(Path(row["summary_path"]))
    conn.close()
    return LLMSummaryResult(
        summarized_count=len(summarized_ids),
        summary_paths=tuple(summary_paths),
        errors=tuple(errors),
    )


def process_item(config: AppConfig, item_id: int) -> RunResult:
    config.settings.reports_dir.mkdir(parents=True, exist_ok=True)
    config.settings.audio_dir.mkdir(parents=True, exist_ok=True)
    config.settings.transcripts_dir.mkdir(parents=True, exist_ok=True)
    config.settings.summaries_dir.mkdir(parents=True, exist_ok=True)

    conn = connect(config.settings.database)
    init_db(conn)
    get_item(conn, item_id)

    transcribed_ids, transcript_errors = process_pending_transcripts(conn, config, [item_id])
    llm_summary_ids, llm_errors = summarize_pending_with_llm(conn, config, [item_id])
    summarized_count = summarize_pending(conn, config, [item_id])

    row = get_item(conn, item_id)
    errors = [*transcript_errors, *llm_errors]
    report_path = write_report(
        config.settings.reports_dir,
        [row],
        errors,
        local_timezone=config.settings.local_timezone,
    )
    conn.close()

    return RunResult(
        new_count=0,
        transcribed_count=len(transcribed_ids),
        llm_summarized_count=len(llm_summary_ids),
        summarized_count=summarized_count,
        report_path=report_path,
        errors=tuple(errors),
    )


def process_pending_transcripts(
    conn: sqlite3.Connection,
    config: AppConfig,
    candidate_ids: list[int],
) -> tuple[list[int], list[str]]:
    if not candidate_ids:
        return [], []

    errors: list[str] = []
    transcribed_ids: list[int] = []
    rows = items_needing_transcript_by_ids(conn, candidate_ids, config.settings.max_transcriptions_per_run)
    rows_to_transcribe: list[tuple[sqlite3.Row, Source | None]] = []
    for row in rows:
        source = _source_for_row(config, row)
        should_transcribe = _source_bool(
            source.transcribe_audio if source is not None else None,
            config.settings.transcribe_audio,
        )
        if should_transcribe:
            rows_to_transcribe.append((row, source))

    if not rows_to_transcribe:
        return [], []

    if not config.settings.whisper_model.exists():
        return [], [f"Whisper model not found: {config.settings.whisper_model}"]

    for row, source in rows_to_transcribe:
        try:
            audio_path = audio_path_for_item(
                config.settings.audio_dir,
                row["source_name"],
                row["title"],
                row["published_at"] or "",
                row["audio_url"],
                config.settings.local_timezone,
            )
            should_download = _source_bool(
                source.download_audio if source is not None else None,
                config.settings.download_audio,
            )
            should_delete = _source_bool(
                source.delete_audio_after_transcription if source is not None else None,
                config.settings.delete_audio_after_transcription,
            )
            if should_download:
                download_audio(row["audio_url"], audio_path)
                update_audio_path(conn, int(row["id"]), audio_path)
            elif row["audio_path"]:
                audio_path = Path(row["audio_path"])
            elif not audio_path.exists():
                raise RuntimeError("audio download disabled and no local audio file found")

            transcript_path = transcript_path_for_item(
                config.settings.transcripts_dir,
                row["source_name"],
                row["title"],
                row["published_at"] or "",
                config.settings.local_timezone,
            )
            transcript = transcribe_audio(
                whisper_command=config.settings.whisper_command,
                ffmpeg_command=config.settings.ffmpeg_command,
                model_path=config.settings.whisper_model,
                language=config.settings.whisper_language,
                audio_path=audio_path,
                transcript_path=transcript_path,
            )
            write_transcript_markdown(
                transcript_path,
                title=row["title"],
                source_name=row["source_name"],
                published_at=row["published_at"] or "",
                link=row["link"] or "",
                audio_path=audio_path,
                transcript=transcript,
            )
            update_transcript(conn, int(row["id"]), transcript, transcript_path)
            if should_delete:
                delete_audio_artifacts(audio_path)
                update_audio_path(conn, int(row["id"]), "")
            update_summary(
                conn,
                int(row["id"]),
                summarize_text(
                    transcript,
                    sentence_count=config.settings.summary_sentences,
                    keywords=config.settings.keywords,
                ),
            )
            transcribed_ids.append(int(row["id"]))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{row['source_name']} / {row['title']}: transcript failed: {exc}")

    return transcribed_ids, errors


def run(config: AppConfig) -> RunResult:
    config.settings.reports_dir.mkdir(parents=True, exist_ok=True)
    config.settings.texts_dir.mkdir(parents=True, exist_ok=True)
    config.settings.audio_dir.mkdir(parents=True, exist_ok=True)
    config.settings.transcripts_dir.mkdir(parents=True, exist_ok=True)
    config.settings.summaries_dir.mkdir(parents=True, exist_ok=True)

    conn = connect(config.settings.database)
    init_db(conn)

    zone = _local_zone(config)
    scan_started_at = datetime.now(timezone.utc).replace(microsecond=0)
    candidate_ids: list[int] = []
    new_ids: list[int] = []
    errors: list[str] = []
    errors_by_source: dict[str, list[str]] = {}
    source_windows: dict[str, tuple[datetime, datetime]] = {}
    for source in config.sources:
        if not source.enabled:
            continue
        scan_window = _scan_window_for_source(conn, config, source, zone, scan_started_at)
        if scan_window is not None:
            source_windows[source.url] = scan_window
        source_candidate_ids, source_new_ids, source_errors = _process_source(
            conn,
            config,
            source,
            zone,
            scan_window,
        )
        candidate_ids.extend(source_candidate_ids)
        new_ids.extend(source_new_ids)
        errors.extend(source_errors)
        errors_by_source.setdefault(source.url, []).extend(source_errors)

    candidate_ids = list(dict.fromkeys(candidate_ids))
    transcribed_ids, transcript_errors = process_pending_transcripts(conn, config, candidate_ids)
    errors.extend(transcript_errors)
    for error in transcript_errors:
        source_url = _source_url_for_error(config, error)
        if source_url:
            errors_by_source.setdefault(source_url, []).append(error)

    llm_candidates = list(dict.fromkeys([*candidate_ids, *transcribed_ids]))
    llm_summary_ids, llm_errors = summarize_pending_with_llm(conn, config, llm_candidates)
    errors.extend(llm_errors)
    for error in llm_errors:
        source_url = _source_url_for_error(config, error)
        if source_url:
            errors_by_source.setdefault(source_url, []).append(error)

    summarized_count = summarize_pending(conn, config, candidate_ids)
    report_ids = list(dict.fromkeys([*candidate_ids, *transcribed_ids, *llm_summary_ids]))
    report_items = [get_item(conn, item_id) for item_id in report_ids]
    report_path = write_report(
        config.settings.reports_dir,
        report_items,
        errors,
        local_timezone=config.settings.local_timezone,
    )
    for source in config.sources:
        if not source.enabled or source.url not in source_windows:
            continue
        if not errors_by_source.get(source.url):
            set_state(conn, _source_state_key(source), source_windows[source.url][1].isoformat())
    conn.close()

    return RunResult(
        new_count=len(new_ids),
        transcribed_count=len(transcribed_ids),
        llm_summarized_count=len(llm_summary_ids),
        summarized_count=summarized_count,
        report_path=report_path,
        errors=tuple(errors),
    )

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from .rss import utc_now_iso


@dataclass(frozen=True)
class StoredItem:
    id: int
    is_new: bool


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            source_url TEXT NOT NULL,
            guid TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT,
            published_at TEXT,
            first_seen_at TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            audio_url TEXT,
            audio_type TEXT,
            audio_path TEXT,
            duration TEXT,
            image_url TEXT,
            raw_text TEXT,
            text TEXT,
            text_path TEXT,
            transcript TEXT,
            transcript_path TEXT,
            transcribed_at TEXT,
            summary TEXT,
            summary_kind TEXT,
            summary_model TEXT,
            summary_path TEXT,
            summary_updated_at TEXT,
            UNIQUE(source_url, guid)
        )
        """
    )
    _ensure_column(conn, "items", "audio_path", "TEXT")
    _ensure_column(conn, "items", "transcript", "TEXT")
    _ensure_column(conn, "items", "transcript_path", "TEXT")
    _ensure_column(conn, "items", "transcribed_at", "TEXT")
    _ensure_column(conn, "items", "summary_kind", "TEXT")
    _ensure_column(conn, "items", "summary_model", "TEXT")
    _ensure_column(conn, "items", "summary_path", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_first_seen ON items(first_seen_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_name)")
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def upsert_item(
    conn: sqlite3.Connection,
    *,
    source_name: str,
    source_url: str,
    guid: str,
    title: str,
    link: str,
    published_at: str,
    audio_url: str,
    audio_type: str,
    duration: str,
    image_url: str,
    raw_text: str,
    text: str,
) -> StoredItem:
    now = utc_now_iso()
    existing = conn.execute(
        "SELECT id FROM items WHERE source_url = ? AND guid = ?",
        (source_url, guid),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE items
               SET title = ?,
                   link = ?,
                   published_at = ?,
                   fetched_at = ?,
                   audio_url = ?,
                   audio_type = ?,
                   duration = ?,
                   image_url = ?,
                   raw_text = ?,
                   text = ?
             WHERE id = ?
            """,
            (
                title,
                link,
                published_at,
                now,
                audio_url,
                audio_type,
                duration,
                image_url,
                raw_text,
                text,
                existing["id"],
            ),
        )
        conn.commit()
        return StoredItem(id=int(existing["id"]), is_new=False)

    cur = conn.execute(
        """
        INSERT INTO items (
            source_name, source_url, guid, title, link, published_at,
            first_seen_at, fetched_at, audio_url, audio_type, duration,
            image_url, raw_text, text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_name,
            source_url,
            guid,
            title,
            link,
            published_at,
            now,
            now,
            audio_url,
            audio_type,
            duration,
            image_url,
            raw_text,
            text,
        ),
    )
    conn.commit()
    return StoredItem(id=int(cur.lastrowid), is_new=True)


def update_text_path(conn: sqlite3.Connection, item_id: int, text_path: Path) -> None:
    conn.execute("UPDATE items SET text_path = ? WHERE id = ?", (str(text_path), item_id))
    conn.commit()


def update_audio_path(conn: sqlite3.Connection, item_id: int, audio_path: Path | str) -> None:
    conn.execute("UPDATE items SET audio_path = ? WHERE id = ?", (str(audio_path), item_id))
    conn.commit()


def update_transcript(conn: sqlite3.Connection, item_id: int, transcript: str, transcript_path: Path) -> None:
    conn.execute(
        "UPDATE items SET transcript = ?, transcript_path = ?, transcribed_at = ? WHERE id = ?",
        (transcript, str(transcript_path), utc_now_iso(), item_id),
    )
    conn.commit()


def update_summary(
    conn: sqlite3.Connection,
    item_id: int,
    summary: str,
    *,
    kind: str = "local",
    model: str = "",
    summary_path: Path | None = None,
) -> None:
    conn.execute(
        """
        UPDATE items
           SET summary = ?,
               summary_kind = ?,
               summary_model = ?,
               summary_path = ?,
               summary_updated_at = ?
         WHERE id = ?
        """,
        (summary, kind, model, str(summary_path) if summary_path else "", utc_now_iso(), item_id),
    )
    conn.commit()


def get_item(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(f"Item not found: {item_id}")
    return row


def items_without_summary(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM items
             WHERE COALESCE(summary, '') = ''
             ORDER BY first_seen_at DESC
            """
        )
    )


def items_without_summary_by_ids(conn: sqlite3.Connection, item_ids: list[int]) -> list[sqlite3.Row]:
    if not item_ids:
        return []
    placeholders = ",".join("?" for _ in item_ids)
    return list(
        conn.execute(
            f"""
            SELECT * FROM items
             WHERE id IN ({placeholders})
               AND COALESCE(summary, '') = ''
             ORDER BY first_seen_at DESC
            """,
            tuple(item_ids),
        )
    )


def items_needing_llm_summary(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    limit_sql = "" if limit <= 0 else "LIMIT ?"
    params: tuple[int, ...] = () if limit <= 0 else (limit,)
    return list(
        conn.execute(
            f"""
            SELECT * FROM items
             WHERE COALESCE(transcript, '') != ''
               AND COALESCE(summary_kind, '') != 'llm'
             ORDER BY transcribed_at DESC, first_seen_at DESC
             {limit_sql}
            """,
            params,
        )
    )


def items_needing_llm_summary_by_ids(conn: sqlite3.Connection, item_ids: list[int], limit: int) -> list[sqlite3.Row]:
    if not item_ids:
        return []
    placeholders = ",".join("?" for _ in item_ids)
    limit_sql = "" if limit <= 0 else "LIMIT ?"
    params = tuple(item_ids) if limit <= 0 else (*item_ids, limit)
    return list(
        conn.execute(
            f"""
            SELECT * FROM items
             WHERE id IN ({placeholders})
               AND COALESCE(transcript, '') != ''
               AND COALESCE(summary_kind, '') != 'llm'
             ORDER BY transcribed_at DESC, first_seen_at DESC
             {limit_sql}
            """,
            params,
        )
    )


def items_needing_transcript(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    limit_sql = "" if limit <= 0 else "LIMIT ?"
    params: tuple[int, ...] = () if limit <= 0 else (limit,)
    return list(
        conn.execute(
            f"""
            SELECT * FROM items
             WHERE COALESCE(audio_url, '') != ''
               AND COALESCE(transcript_path, '') = ''
             ORDER BY first_seen_at DESC
             {limit_sql}
            """,
            params,
        )
    )


def items_needing_transcript_by_ids(conn: sqlite3.Connection, item_ids: list[int], limit: int) -> list[sqlite3.Row]:
    if not item_ids:
        return []
    placeholders = ",".join("?" for _ in item_ids)
    limit_sql = "" if limit <= 0 else "LIMIT ?"
    params = tuple(item_ids) if limit <= 0 else (*item_ids, limit)
    return list(
        conn.execute(
            f"""
            SELECT * FROM items
             WHERE id IN ({placeholders})
               AND COALESCE(audio_url, '') != ''
               AND COALESCE(transcript_path, '') = ''
             ORDER BY first_seen_at DESC
             {limit_sql}
            """,
            params,
        )
    )


def latest_items(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM items ORDER BY first_seen_at DESC LIMIT ?",
            (limit,),
        )
    )

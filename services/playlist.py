"""SQLite-backed shared playlist operations."""

from datetime import datetime, timezone
import sqlite3

from config.database import connection


def _list_playlist(database: sqlite3.Connection) -> list[dict[str, object]]:
    rows = database.execute(
        """
        SELECT tracks.*
        FROM playlist_items
        JOIN tracks ON tracks.id = playlist_items.track_id
        ORDER BY playlist_items.position, tracks.title COLLATE NOCASE
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _sync_broadcast_next_track(database: sqlite3.Connection) -> None:
    row = database.execute(
        "SELECT track_id FROM playlist_items ORDER BY position LIMIT 1"
    ).fetchone()
    next_track_id = str(row["track_id"]) if row is not None else None
    database.execute(
        """
        UPDATE broadcast_state
        SET next_track_id = ?, revision = revision + 1, updated_at = ?
        WHERE id = 1
        """,
        (next_track_id, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )


def list_playlist() -> list[dict[str, object]]:
    with connection() as database:
        return _list_playlist(database)


def add_track(track_id: str) -> list[dict[str, object]]:
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        if database.execute(
            "SELECT 1 FROM tracks WHERE id = ?", (track_id,)
        ).fetchone() is None:
            raise ValueError("Track not found.")
        exists = database.execute(
            "SELECT 1 FROM playlist_items WHERE track_id = ?", (track_id,)
        ).fetchone()
        if exists is None:
            row = database.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS position FROM playlist_items"
            ).fetchone()
            database.execute(
                "INSERT INTO playlist_items (track_id, position) VALUES (?, ?)",
                (track_id, int(row["position"])),
            )
        _sync_broadcast_next_track(database)
        return _list_playlist(database)


def play_track_next(track_id: str) -> list[dict[str, object]]:
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        if database.execute(
            "SELECT 1 FROM tracks WHERE id = ?", (track_id,)
        ).fetchone() is None:
            raise ValueError("Track not found.")
        database.execute("DELETE FROM playlist_items WHERE track_id = ?", (track_id,))
        database.execute("UPDATE playlist_items SET position = position + 1")
        database.execute(
            "INSERT INTO playlist_items (track_id, position) VALUES (?, 0)",
            (track_id,),
        )
        _sync_broadcast_next_track(database)
        return _list_playlist(database)


def remove_track(track_id: str) -> list[dict[str, object]]:
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        database.execute("DELETE FROM playlist_items WHERE track_id = ?", (track_id,))
        _sync_broadcast_next_track(database)
        return _list_playlist(database)


def sync_broadcast_next_track() -> None:
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        _sync_broadcast_next_track(database)

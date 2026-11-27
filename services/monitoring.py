"""Persist local playback and application activity."""

from datetime import datetime, timezone

from config.database import connection


def record_event(
    *, event_type: str, message: str, track_id: str | None = None
) -> dict[str, object]:
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connection() as database:
        cursor = database.execute(
            """
            INSERT INTO monitor_events (event_type, message, track_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (event_type, message, track_id, created_at),
        )
        row = database.execute(
            "SELECT * FROM monitor_events WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    if row is None:
        raise RuntimeError("The monitoring event was not saved.")
    return dict(row)


def list_events(limit: int = 100) -> list[dict[str, object]]:
    with connection() as database:
        rows = database.execute(
            """
            SELECT monitor_events.*, tracks.title AS track_title
            FROM monitor_events
            LEFT JOIN tracks ON tracks.id = monitor_events.track_id
            ORDER BY monitor_events.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]

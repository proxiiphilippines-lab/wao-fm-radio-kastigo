"""Local current-track state shared with the guest listener page."""

from datetime import datetime, timezone
import math

from config.database import connection
from services import music_library


def current_state() -> dict[str, object]:
    with connection() as database:
        row = database.execute(
            """
            SELECT track_id, next_track_id, controller_id, is_playing,
                   position_seconds, revision, updated_at
            FROM broadcast_state
            WHERE id = 1
            """
        ).fetchone()
    if row is None:
        raise RuntimeError("Broadcast state has not been initialized.")
    track = (
        music_library.get_track(str(row["track_id"]))
        if row["track_id"] is not None
        else None
    )
    next_track = (
        music_library.get_track(str(row["next_track_id"]))
        if row["next_track_id"] is not None
        else None
    )
    return {
        "track": track,
        "next_track": next_track,
        "controller_id": (
            str(row["controller_id"]) if row["controller_id"] is not None else None
        ),
        "is_playing": bool(row["is_playing"]),
        "position_seconds": float(row["position_seconds"]),
        "revision": int(row["revision"]),
        "updated_at": str(row["updated_at"]),
    }


def set_next_track(next_track_id: str | None) -> None:
    if next_track_id is not None and music_library.get_track(next_track_id) is None:
        raise ValueError("Next track not found.")

    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connection() as database:
        cursor = database.execute(
            """
            UPDATE broadcast_state
            SET next_track_id = ?, revision = revision + 1, updated_at = ?
            WHERE id = 1
            """,
            (next_track_id, updated_at),
        )
    if cursor.rowcount == 0:
        raise RuntimeError("Broadcast state has not been initialized.")


def set_current_state(
    *,
    controller_id: str,
    track_id: str | None,
    is_playing: bool,
    position_seconds: float,
) -> dict[str, object]:
    if not math.isfinite(position_seconds) or position_seconds < 0:
        raise ValueError("Playback position must be a nonnegative finite number.")
    if track_id is not None and music_library.get_track(track_id) is None:
        raise ValueError("Track not found.")
    if track_id is None and is_playing:
        raise ValueError("Cannot mark the broadcast as playing without a track.")

    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connection() as database:
        cursor = database.execute(
            """
            UPDATE broadcast_state
            SET track_id = ?, is_playing = ?, position_seconds = ?,
                revision = revision + 1, updated_at = ?
            WHERE id = 1 AND controller_id = ?
            """,
            (
                track_id,
                int(is_playing),
                max(0, position_seconds),
                updated_at,
                controller_id,
            ),
        )
        if cursor.rowcount == 0:
            row = database.execute(
                "SELECT 1 FROM broadcast_state WHERE id = 1"
            ).fetchone()
            if row is None:
                raise RuntimeError("Broadcast state has not been initialized.")
            raise PermissionError("Playback control was taken by another operator.")
    return current_state()


def clear_current_state() -> None:
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connection() as database:
        database.execute(
            """
            UPDATE broadcast_state
            SET track_id = NULL, is_playing = 0, position_seconds = 0,
                controller_id = NULL, revision = revision + 1, updated_at = ?
            WHERE id = 1
            """,
            (updated_at,),
        )


def claim_control(
    *,
    controller_id: str,
    track_id: str,
    position_seconds: float = 0,
) -> dict[str, object]:
    if not controller_id:
        raise ValueError("A playback controller ID is required.")
    if not math.isfinite(position_seconds) or position_seconds < 0:
        raise ValueError("Playback position must be a nonnegative finite number.")
    if music_library.get_track(track_id) is None:
        raise ValueError("Track not found.")

    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connection() as database:
        cursor = database.execute(
            """
            UPDATE broadcast_state
            SET controller_id = ?, track_id = ?, is_playing = 1,
                position_seconds = ?, revision = revision + 1, updated_at = ?
            WHERE id = 1
            """,
            (
                controller_id,
                track_id,
                max(0, position_seconds),
                updated_at,
            ),
        )
        if cursor.rowcount == 0:
            raise RuntimeError("Broadcast state has not been initialized.")
    return current_state()


def is_current_track(track_id: str) -> bool:
    with connection() as database:
        row = database.execute(
            """
            SELECT 1
            FROM broadcast_state
            WHERE id = 1 AND (track_id = ? OR next_track_id = ?)
            """,
            (track_id, track_id),
        ).fetchone()
    return row is not None

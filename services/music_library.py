"""SQLite-backed music library operations."""

import hashlib
import logging
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from mutagen import File as read_audio_file
from mutagen import MutagenError

from config.database import connection

LOGGER = logging.getLogger(__name__)


class DuplicateTrackError(ValueError):
    """Raised when an audio file's contents already exist in the library."""


def audio_file_hash(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as audio_file:
        while chunk := audio_file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def backfill_track_hashes() -> None:
    with connection() as database:
        tracks = database.execute(
            "SELECT id, file_name, file_path FROM tracks WHERE content_hash IS NULL"
        ).fetchall()
    for track in tracks:
        try:
            digest = audio_file_hash(Path(str(track["file_path"])))
        except OSError as error:
            LOGGER.warning(
                "Could not calculate a content hash for existing track %s: %s",
                track["file_name"],
                error,
            )
            continue
        try:
            with connection() as database:
                database.execute(
                    """
                    UPDATE tracks SET content_hash = ?
                    WHERE id = ? AND content_hash IS NULL
                    """,
                    (digest, track["id"]),
                )
        except sqlite3.IntegrityError:
            LOGGER.warning(
                "Existing track %s duplicates another library file.",
                track["file_name"],
            )


def audio_duration_seconds(file_path: Path) -> float:
    try:
        audio = read_audio_file(file_path)
    except (MutagenError, OSError) as error:
        raise ValueError("The audio file's duration could not be read.") from error
    if audio is None or audio.info is None:
        raise ValueError("The audio file's duration could not be read.")
    duration = float(audio.info.length)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("The audio file has an invalid duration.")
    return duration


def backfill_track_durations() -> None:
    with connection() as database:
        tracks = database.execute(
            """
            SELECT id, file_name, file_path
            FROM tracks
            WHERE duration_seconds IS NULL
            """
        ).fetchall()
    for track in tracks:
        try:
            duration = audio_duration_seconds(Path(str(track["file_path"])))
        except (MutagenError, OSError, ValueError) as error:
            LOGGER.warning(
                "Could not read duration for existing track %s: %s",
                track["file_name"],
                error,
            )
            continue
        with connection() as database:
            database.execute(
                "UPDATE tracks SET duration_seconds = ? WHERE id = ?",
                (duration, track["id"]),
            )


def register_track(
    *,
    title: str,
    artist: str,
    file_name: str,
    file_path: Path,
    content_type: str,
    size_bytes: int,
    category: str = "music",
    duration_seconds: float | None = None,
) -> dict[str, object]:
    category = " ".join(category.split())
    if not category or len(category) > 80 or any(ord(char) < 32 for char in category):
        raise ValueError("Category must be between 1 and 80 valid characters.")
    if duration_seconds is not None and (
        not math.isfinite(duration_seconds) or duration_seconds <= 0
    ):
        raise ValueError("Track duration must be a positive finite number.")
    track_id = uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    content_hash = audio_file_hash(file_path)
    with connection() as database:
        duplicate = database.execute(
            "SELECT file_name FROM tracks WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if duplicate is not None:
            raise DuplicateTrackError(
                f"This file duplicates the existing track {duplicate['file_name']}."
            )
        try:
            database.execute(
                """
                INSERT INTO tracks
                    (id, title, artist, file_name, file_path, content_type, category,
                     duration_seconds, size_bytes, content_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    track_id,
                    title,
                    artist,
                    file_name,
                    str(file_path),
                    content_type,
                    category,
                    duration_seconds,
                    size_bytes,
                    content_hash,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as error:
            duplicate = database.execute(
                "SELECT file_name FROM tracks WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
            if duplicate is None:
                raise
            raise DuplicateTrackError(
                f"This file duplicates the existing track {duplicate['file_name']}."
            ) from error
        row = database.execute(
            "SELECT * FROM tracks WHERE id = ?", (track_id,)
        ).fetchone()
    if row is None:
        raise RuntimeError("The uploaded track was not saved.")
    return dict(row)


def list_tracks() -> list[dict[str, object]]:
    with connection() as database:
        rows = database.execute(
            "SELECT * FROM tracks ORDER BY created_at DESC, title COLLATE NOCASE"
        ).fetchall()
    return [dict(row) for row in rows]


def get_track(track_id: str) -> dict[str, object] | None:
    with connection() as database:
        row = database.execute(
            "SELECT * FROM tracks WHERE id = ?", (track_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def delete_track(track_id: str) -> dict[str, object] | None:
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        row = database.execute(
            "SELECT * FROM tracks WHERE id = ?", (track_id,)
        ).fetchone()
        if row is None:
            return None

        state = database.execute(
            "SELECT track_id FROM broadcast_state WHERE id = 1"
        ).fetchone()
        if state is not None and state["track_id"] == track_id:
            database.execute(
                """
                UPDATE broadcast_state
                SET track_id = NULL, is_playing = 0, position_seconds = 0,
                    controller_id = NULL
                WHERE id = 1
                """
            )

        database.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        next_track = database.execute(
            "SELECT track_id FROM playlist_items ORDER BY position LIMIT 1"
        ).fetchone()
        database.execute(
            """
            UPDATE broadcast_state
            SET next_track_id = ?, revision = revision + 1, updated_at = ?
            WHERE id = 1
            """,
            (
                str(next_track["track_id"]) if next_track is not None else None,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
    return dict(row)


def track_count() -> int:
    with connection() as database:
        row = database.execute("SELECT COUNT(*) AS count FROM tracks").fetchone()
    if row is None:
        raise RuntimeError("Unable to count saved tracks.")
    return int(row["count"])


def track_file_path(track: dict[str, object]) -> Path:
    file_path = Path(str(track["file_path"]))
    if not file_path.is_file():
        raise FileNotFoundError(f"Audio file is missing: {track['file_name']}")
    return file_path

"""Focused tests for SQLite music and monitoring persistence."""

import sqlite3
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from config.database import initialize_database
from services.broadcast import (
    claim_control,
    current_state,
    is_current_track,
    set_current_state,
    set_next_track,
)
from services.monitoring import list_events, record_event
from services.music_library import (
    DuplicateTrackError,
    audio_duration_seconds,
    backfill_track_durations,
    backfill_track_hashes,
    delete_track,
    list_tracks,
    register_track,
    track_count,
)
from services.playlist import (
    add_track,
    list_playlist,
    play_track_next,
    remove_track,
)


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = Path(self.temporary_directory.name) / "test.sqlite3"
        self.database_patch = patch("config.database.DATABASE_PATH", self.database_path)
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)
        initialize_database()

    def test_registered_track_and_playback_event_are_persisted(self) -> None:
        audio_path = Path(self.temporary_directory.name) / "demo.mp3"
        audio_path.write_bytes(b"audio")
        track = register_track(
            title="Demo",
            artist="Station",
            file_name="demo.mp3",
            file_path=audio_path,
            content_type="audio/mpeg",
            size_bytes=5,
        )

        self.assertEqual(track_count(), 1)
        self.assertEqual(list_tracks()[0]["id"], track["id"])
        event = record_event(
            event_type="playback_started",
            message="Started playing Demo",
            track_id=str(track["id"]),
        )
        saved_events = list_events()
        self.assertEqual(event["id"], saved_events[0]["id"])
        self.assertEqual(saved_events[0]["track_title"], "Demo")

    def test_audio_duration_is_read_and_backfilled_from_the_file(self) -> None:
        audio_path = Path(self.temporary_directory.name) / "duration.wav"
        with wave.open(str(audio_path), "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(8000)
            audio_file.writeframes(b"\0\0" * 20000)

        measured_duration = audio_duration_seconds(audio_path)
        self.assertAlmostEqual(measured_duration, 2.5)
        track = register_track(
            title="Duration test",
            artist="Station",
            file_name=audio_path.name,
            file_path=audio_path,
            content_type="audio/wav",
            size_bytes=audio_path.stat().st_size,
        )
        self.assertIsNone(track["duration_seconds"])

        backfill_track_durations()
        self.assertAlmostEqual(float(list_tracks()[0]["duration_seconds"]), 2.5)

    def test_track_category_supports_folder_names(self) -> None:
        audio_path = Path(self.temporary_directory.name) / "ad.mp3"
        audio_path.write_bytes(b"audio")
        track = register_track(
            title="Station spot",
            artist="Station",
            file_name="ad.mp3",
            file_path=audio_path,
            content_type="audio/mpeg",
            size_bytes=5,
            category="advertisement",
        )

        self.assertEqual(track["category"], "advertisement")
        self.assertEqual(list_tracks()[0]["category"], "advertisement")
        set_next_track(str(track["id"]))
        self.assertEqual(current_state()["next_track"]["category"], "advertisement")

        custom_path = Path(self.temporary_directory.name) / "custom.mp3"
        custom_path.write_bytes(b"different audio")
        custom = register_track(
            title="Custom category track",
            artist="Station",
            file_name="custom.mp3",
            file_path=custom_path,
            content_type="audio/mpeg",
            size_bytes=custom_path.stat().st_size,
            category="Sunday Worship",
        )
        self.assertEqual(custom["category"], "Sunday Worship")

        with self.assertRaisesRegex(ValueError, "Category"):
            register_track(
                title="Invalid",
                artist="Station",
                file_name="invalid.mp3",
                file_path=audio_path,
                content_type="audio/mpeg",
                size_bytes=5,
                category=" ",
            )

    def test_duplicate_audio_contents_are_rejected_even_with_different_names(self) -> None:
        first_path = Path(self.temporary_directory.name) / "first.mp3"
        first_path.write_bytes(b"identical audio content")
        register_track(
            title="First",
            artist="Station",
            file_name=first_path.name,
            file_path=first_path,
            content_type="audio/mpeg",
            size_bytes=first_path.stat().st_size,
        )

        second_path = Path(self.temporary_directory.name) / "renamed-copy.mp3"
        second_path.write_bytes(first_path.read_bytes())
        with self.assertRaisesRegex(DuplicateTrackError, "duplicates"):
            register_track(
                title="Copy",
                artist="Station",
                file_name=second_path.name,
                file_path=second_path,
                content_type="audio/mpeg",
                size_bytes=second_path.stat().st_size,
            )
        self.assertEqual(track_count(), 1)

    def test_existing_library_tracks_are_included_in_duplicate_checks(self) -> None:
        legacy_path = Path(self.temporary_directory.name) / "legacy-hash.sqlite3"
        legacy_audio = Path(self.temporary_directory.name) / "old-track.mp3"
        legacy_audio.write_bytes(b"existing library audio")
        database = sqlite3.connect(legacy_path)
        try:
            database.execute(
                """
                CREATE TABLE tracks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            database.execute(
                """
                INSERT INTO tracks
                    (id, title, artist, file_name, file_path, content_type, size_bytes, created_at)
                VALUES ('legacy', 'Old track', 'Station', 'old-track.mp3', ?, 'audio/mpeg',
                        ?, '2026-01-01')
                """,
                (str(legacy_audio), legacy_audio.stat().st_size),
            )
            database.commit()
        finally:
            database.close()

        with patch("config.database.DATABASE_PATH", legacy_path):
            initialize_database()
            backfill_track_hashes()
            duplicate_path = Path(self.temporary_directory.name) / "copy.mp3"
            duplicate_path.write_bytes(legacy_audio.read_bytes())
            with self.assertRaisesRegex(DuplicateTrackError, "duplicates"):
                register_track(
                    title="Copy",
                    artist="Station",
                    file_name=duplicate_path.name,
                    file_path=duplicate_path,
                    content_type="audio/mpeg",
                    size_bytes=duplicate_path.stat().st_size,
                )

    def test_category_constraint_migration_preserves_track_references(self) -> None:
        legacy_path = Path(self.temporary_directory.name) / "category-check.sqlite3"
        database = sqlite3.connect(legacy_path)
        try:
            database.execute("PRAGMA foreign_keys = ON")
            database.executescript(
                """
                CREATE TABLE tracks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    content_type TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'music'
                        CHECK (category IN ('music', 'advertisement', 'drama')),
                    duration_seconds REAL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE playlist_items (
                    track_id TEXT PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL
                );
                INSERT INTO tracks
                    (id, title, artist, file_name, file_path, content_type, category,
                     size_bytes, created_at)
                VALUES ('legacy', 'Legacy track', 'Station', 'legacy.mp3', 'legacy.mp3',
                        'audio/mpeg', 'music', 5, '2026-01-01');
                INSERT INTO playlist_items (track_id, position) VALUES ('legacy', 0);
                """
            )
            database.commit()
        finally:
            database.close()

        with patch("config.database.DATABASE_PATH", legacy_path):
            initialize_database()
            folder_path = Path(self.temporary_directory.name) / "folder.mp3"
            folder_path.write_bytes(b"folder audio")
            register_track(
                title="Folder category track",
                artist="Station",
                file_name="folder.mp3",
                file_path=folder_path,
                content_type="audio/mpeg",
                size_bytes=folder_path.stat().st_size,
                category="Community News",
            )

        database = sqlite3.connect(legacy_path)
        try:
            self.assertEqual(
                database.execute(
                    "SELECT category FROM tracks WHERE id = 'legacy'"
                ).fetchone()[0],
                "music",
            )
            self.assertEqual(
                database.execute(
                    "SELECT track_id FROM playlist_items WHERE track_id = 'legacy'"
                ).fetchone()[0],
                "legacy",
            )
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            database.close()

    def test_initialize_database_migrates_existing_tracks_to_music_category(self) -> None:
        legacy_path = Path(self.temporary_directory.name) / "legacy-tracks.sqlite3"
        database = sqlite3.connect(legacy_path)
        try:
            database.execute(
                """
                CREATE TABLE tracks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            database.execute(
                """
                INSERT INTO tracks
                    (id, title, artist, file_name, file_path, content_type, size_bytes, created_at)
                VALUES ('legacy', 'Old track', 'Station', 'old.mp3', 'old.mp3',
                        'audio/mpeg', 5, '2026-01-01')
                """
            )
            database.commit()
        finally:
            database.close()

        with patch("config.database.DATABASE_PATH", legacy_path):
            initialize_database()
            migrated = list_tracks()

        self.assertEqual(migrated[0]["id"], "legacy")
        self.assertEqual(migrated[0]["category"], "music")
        self.assertIsNone(migrated[0]["duration_seconds"])

    def test_next_broadcast_track_is_shared_and_can_be_cleared(self) -> None:
        audio_path = Path(self.temporary_directory.name) / "next.mp3"
        audio_path.write_bytes(b"audio")
        track = register_track(
            title="Next up",
            artist="Station",
            file_name="next.mp3",
            file_path=audio_path,
            content_type="audio/mpeg",
            size_bytes=5,
        )

        set_next_track(str(track["id"]))
        self.assertEqual(current_state()["next_track"]["id"], track["id"])

        set_next_track(None)
        self.assertIsNone(current_state()["next_track"])
        with self.assertRaisesRegex(ValueError, "Next track not found"):
            set_next_track("missing-track")

    def test_current_track_check_uses_open_connection_for_current_and_queued_tracks(self) -> None:
        audio_path = Path(self.temporary_directory.name) / "on-air.mp3"
        audio_path.write_bytes(b"audio")
        track = register_track(
            title="On air",
            artist="Station",
            file_name=audio_path.name,
            file_path=audio_path,
            content_type="audio/mpeg",
            size_bytes=5,
        )
        track_id = str(track["id"])

        self.assertFalse(is_current_track(track_id))
        set_next_track(track_id)
        self.assertTrue(is_current_track(track_id))
        set_next_track(None)
        claim_control(controller_id="admin-tab", track_id=track_id)
        self.assertTrue(is_current_track(track_id))
        self.assertFalse(is_current_track("not-current"))

    def test_deleting_track_clears_live_state_and_synchronizes_playlist_atomically(self) -> None:
        tracks = []
        for name in ("on-air", "next-up"):
            audio_path = Path(self.temporary_directory.name) / f"{name}.mp3"
            audio_path.write_bytes(name.encode())
            tracks.append(
                register_track(
                    title=name,
                    artist="Station",
                    file_name=audio_path.name,
                    file_path=audio_path,
                    content_type="audio/mpeg",
                    size_bytes=audio_path.stat().st_size,
                )
            )
        claim_control(controller_id="admin-tab", track_id=str(tracks[0]["id"]))
        add_track(str(tracks[1]["id"]))

        deleted = delete_track(str(tracks[0]["id"]))

        self.assertEqual(deleted["id"], tracks[0]["id"])
        state = current_state()
        self.assertIsNone(state["track"])
        self.assertFalse(state["is_playing"])
        self.assertIsNone(state["controller_id"])
        self.assertEqual(state["next_track"]["id"], tracks[1]["id"])

    def test_broadcast_playback_control_can_be_taken_over_by_another_operator(self) -> None:
        track_ids = []
        for index, title in enumerate(("DJ track", "Admin track")):
            audio_path = Path(self.temporary_directory.name) / f"{title}.mp3"
            audio_path.write_bytes(f"audio {index}".encode())
            track = register_track(
                title=title,
                artist="Station",
                file_name=audio_path.name,
                file_path=audio_path,
                content_type="audio/mpeg",
                size_bytes=5,
            )
            track_ids.append(str(track["id"]))

        claim_control(controller_id="dj-tab", track_id=track_ids[0])
        set_current_state(
            controller_id="dj-tab",
            track_id=track_ids[0],
            is_playing=True,
            position_seconds=12.5,
        )
        self.assertEqual(current_state()["controller_id"], "dj-tab")
        self.assertEqual(current_state()["position_seconds"], 12.5)

        claim_control(controller_id="admin-tab", track_id=track_ids[1])
        self.assertEqual(current_state()["controller_id"], "admin-tab")
        self.assertEqual(current_state()["track"]["id"], track_ids[1])
        with self.assertRaisesRegex(PermissionError, "taken by another operator"):
            set_current_state(
                controller_id="dj-tab",
                track_id=track_ids[0],
                is_playing=True,
                position_seconds=20,
            )

    def test_playlist_is_shared_ordered_and_updates_broadcast_next_track(self) -> None:
        tracks = []
        for index, title in enumerate(("First", "Second")):
            audio_path = Path(self.temporary_directory.name) / f"{title}.mp3"
            audio_path.write_bytes(f"audio {index}".encode())
            tracks.append(
                register_track(
                    title=title,
                    artist="Station",
                    file_name=audio_path.name,
                    file_path=audio_path,
                    content_type="audio/mpeg",
                    size_bytes=5,
                )
            )

        add_track(str(tracks[0]["id"]))
        add_track(str(tracks[1]["id"]))
        playlist = add_track(str(tracks[0]["id"]))
        self.assertEqual([item["id"] for item in playlist], [tracks[0]["id"], tracks[1]["id"]])
        self.assertEqual(current_state()["next_track"]["id"], tracks[0]["id"])

        playlist = play_track_next(str(tracks[1]["id"]))
        self.assertEqual([item["id"] for item in playlist], [tracks[1]["id"], tracks[0]["id"]])
        self.assertEqual(current_state()["next_track"]["id"], tracks[1]["id"])

        playlist = remove_track(str(tracks[1]["id"]))
        self.assertEqual([item["id"] for item in playlist], [tracks[0]["id"]])
        self.assertEqual(current_state()["next_track"]["id"], tracks[0]["id"])
        self.assertEqual(remove_track(str(tracks[0]["id"])), [])
        self.assertIsNone(current_state()["next_track"])

        with self.assertRaisesRegex(ValueError, "Track not found"):
            add_track("missing-track")

    def test_initialize_database_adds_next_track_to_existing_broadcast_state(self) -> None:
        legacy_path = Path(self.temporary_directory.name) / "legacy.sqlite3"
        database = sqlite3.connect(legacy_path)
        try:
            database.execute(
                """
                CREATE TABLE broadcast_state (
                    id INTEGER PRIMARY KEY,
                    track_id TEXT,
                    is_playing INTEGER NOT NULL DEFAULT 0,
                    position_seconds REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            database.execute(
                """
                INSERT INTO broadcast_state (id, updated_at)
                VALUES (1, CURRENT_TIMESTAMP)
                """
            )
            database.commit()
        finally:
            database.close()

        with patch("config.database.DATABASE_PATH", legacy_path):
            initialize_database()

        database = sqlite3.connect(legacy_path)
        try:
            columns = {
                row[1] for row in database.execute("PRAGMA table_info(broadcast_state)")
            }
        finally:
            database.close()
        self.assertIn("next_track_id", columns)
        self.assertIn("controller_id", columns)
        self.assertIn("revision", columns)

    def test_initialize_database_stops_unowned_legacy_playback(self) -> None:
        legacy_path = Path(self.temporary_directory.name) / "legacy-playback.sqlite3"
        database = sqlite3.connect(legacy_path)
        try:
            database.execute(
                """
                CREATE TABLE tracks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            database.execute(
                """
                INSERT INTO tracks
                    (id, title, artist, file_name, file_path, content_type, size_bytes, created_at)
                VALUES ('legacy', 'Old track', 'Station', 'old.mp3', 'old.mp3',
                        'audio/mpeg', 5, '2026-01-01')
                """
            )
            database.execute(
                """
                CREATE TABLE broadcast_state (
                    id INTEGER PRIMARY KEY,
                    track_id TEXT,
                    is_playing INTEGER NOT NULL DEFAULT 0,
                    position_seconds REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            database.execute(
                """
                INSERT INTO broadcast_state (id, track_id, is_playing, position_seconds, updated_at)
                VALUES (1, 'legacy', 1, 23, CURRENT_TIMESTAMP)
                """
            )
            database.commit()
        finally:
            database.close()

        with patch("config.database.DATABASE_PATH", legacy_path):
            initialize_database()
            state = current_state()

        self.assertIsNone(state["track"])
        self.assertFalse(state["is_playing"])
        self.assertEqual(state["position_seconds"], 0)

    def test_initialize_database_migrates_existing_next_track_to_shared_playlist(self) -> None:
        legacy_path = Path(self.temporary_directory.name) / "legacy-playlist.sqlite3"
        database = sqlite3.connect(legacy_path)
        try:
            database.execute(
                """
                CREATE TABLE tracks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            database.execute(
                """
                INSERT INTO tracks
                    (id, title, artist, file_name, file_path, content_type, size_bytes, created_at)
                VALUES ('legacy', 'Legacy track', 'Station', 'legacy.mp3', 'legacy.mp3',
                        'audio/mpeg', 5, '2026-01-01')
                """
            )
            database.execute(
                """
                CREATE TABLE broadcast_state (
                    id INTEGER PRIMARY KEY,
                    track_id TEXT,
                    next_track_id TEXT,
                    is_playing INTEGER NOT NULL DEFAULT 0,
                    position_seconds REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            database.execute(
                """
                INSERT INTO broadcast_state (id, next_track_id, updated_at)
                VALUES (1, 'legacy', CURRENT_TIMESTAMP)
                """
            )
            database.commit()
        finally:
            database.close()

        with patch("config.database.DATABASE_PATH", legacy_path):
            initialize_database()
            migrated = list_playlist()

        self.assertEqual([track["id"] for track in migrated], ["legacy"])


if __name__ == "__main__":
    unittest.main()

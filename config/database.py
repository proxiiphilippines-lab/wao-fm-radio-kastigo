"""SQLite connection and schema management."""

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from config.settings import DATABASE_PATH


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(DATABASE_PATH)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys = ON")
    try:
        yield database
        database.commit()
    except Exception:
        database.rollback()
        raise
    finally:
        database.close()


def initialize_database() -> None:
    with connection() as database:
        database.execute("PRAGMA foreign_keys = OFF")
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS tracks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL UNIQUE,
                content_type TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'music',
                duration_seconds REAL CHECK (duration_seconds IS NULL OR duration_seconds > 0),
                size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                content_hash TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS monitor_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                track_id TEXT REFERENCES tracks(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'dj')),
                must_change_password INTEGER NOT NULL DEFAULT 0
                    CHECK (must_change_password IN (0, 1)),
                is_banned INTEGER NOT NULL DEFAULT 0
                    CHECK (is_banned IN (0, 1)),
                created_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_single_station_admin
                ON users(role)
                WHERE role = 'admin';

            CREATE TABLE IF NOT EXISTS dj_applications (
                id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                experience TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                assigned_username TEXT,
                submitted_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by TEXT REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_dj_application_email
                ON dj_applications(email COLLATE NOCASE)
                WHERE status = 'pending';

            CREATE TABLE IF NOT EXISTS ad_applications (
                id TEXT PRIMARY KEY,
                contact_name TEXT NOT NULL,
                business_name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                ad_details TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'reviewed')),
                submitted_at TEXT NOT NULL,
                reviewed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS live_ad (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                text TEXT NOT NULL DEFAULT '',
                image_filename TEXT,
                image_content_type TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS live_ad_images (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL UNIQUE,
                content_type TEXT NOT NULL,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                ad_id INTEGER NOT NULL DEFAULT 1
                    REFERENCES live_ad(id) ON DELETE CASCADE,
                UNIQUE (ad_id, sort_order)
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS auth_login_attempts (
                username TEXT PRIMARY KEY COLLATE NOCASE,
                failed_attempts INTEGER NOT NULL,
                window_started_at INTEGER NOT NULL,
                locked_until INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS public_rate_limits (
                scope TEXT NOT NULL,
                client_hash TEXT NOT NULL,
                window_started_at INTEGER NOT NULL,
                request_count INTEGER NOT NULL,
                PRIMARY KEY (scope, client_hash)
            );

            CREATE TABLE IF NOT EXISTS broadcast_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                track_id TEXT REFERENCES tracks(id) ON DELETE SET NULL,
                next_track_id TEXT REFERENCES tracks(id) ON DELETE SET NULL,
                controller_id TEXT,
                is_playing INTEGER NOT NULL DEFAULT 0 CHECK (is_playing IN (0, 1)),
                position_seconds REAL NOT NULL DEFAULT 0 CHECK (position_seconds >= 0),
                revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS playlist_items (
                track_id TEXT PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
                position INTEGER NOT NULL CHECK (position >= 0)
            );
            """
        )
        user_columns = {
            str(row["name"])
            for row in database.execute("PRAGMA table_info(users)").fetchall()
        }
        if "is_banned" not in user_columns:
            database.execute(
                """
                ALTER TABLE users
                ADD COLUMN is_banned INTEGER NOT NULL DEFAULT 0
                    CHECK (is_banned IN (0, 1))
                """
            )
        track_columns = {
            str(row["name"])
            for row in database.execute("PRAGMA table_info(tracks)").fetchall()
        }
        if "category" not in track_columns:
            database.execute(
                """
                ALTER TABLE tracks
                ADD COLUMN category TEXT NOT NULL DEFAULT 'music'
                """
            )
        if "duration_seconds" not in track_columns:
            database.execute(
                """
                ALTER TABLE tracks
                ADD COLUMN duration_seconds REAL
                    CHECK (duration_seconds IS NULL OR duration_seconds > 0)
                """
            )
        if "content_hash" not in track_columns:
            database.execute("ALTER TABLE tracks ADD COLUMN content_hash TEXT")

        track_schema = database.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'tracks'"
        ).fetchone()
        if track_schema and re.search(
            r"CHECK\s*\(\s*category\s+IN\s*\(",
            str(track_schema["sql"]),
            re.IGNORECASE,
        ):
            database.execute(
                """
                CREATE TABLE tracks_migrated (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    artist TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    content_type TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'music',
                    duration_seconds REAL
                        CHECK (duration_seconds IS NULL OR duration_seconds > 0),
                    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
                    content_hash TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            database.execute(
                """
                INSERT INTO tracks_migrated
                    (id, title, artist, file_name, file_path, content_type, category,
                     duration_seconds, size_bytes, content_hash, created_at)
                SELECT id, title, artist, file_name, file_path, content_type, category,
                       duration_seconds, size_bytes, content_hash, created_at
                FROM tracks
                """
            )
            database.execute("DROP TABLE tracks")
            database.execute("ALTER TABLE tracks_migrated RENAME TO tracks")
        database.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_content_hash
            ON tracks(content_hash)
            WHERE content_hash IS NOT NULL
            """
        )
        database.execute(
            """
            INSERT OR IGNORE INTO live_ad_images
                (id, filename, content_type, sort_order, created_at, ad_id)
            SELECT image_filename, image_filename, image_content_type, 0, updated_at, id
            FROM live_ad
            WHERE image_filename IS NOT NULL
            """
        )
        broadcast_columns = {
            str(row["name"])
            for row in database.execute("PRAGMA table_info(broadcast_state)").fetchall()
        }
        if "next_track_id" not in broadcast_columns:
            database.execute(
                """
                ALTER TABLE broadcast_state
                ADD COLUMN next_track_id TEXT REFERENCES tracks(id) ON DELETE SET NULL
                """
            )
        if "controller_id" not in broadcast_columns:
            database.execute(
                "ALTER TABLE broadcast_state ADD COLUMN controller_id TEXT"
            )
        if "revision" not in broadcast_columns:
            database.execute(
                """
                ALTER TABLE broadcast_state
                ADD COLUMN revision INTEGER NOT NULL DEFAULT 0
                    CHECK (revision >= 0)
                """
            )
        database.execute(
            """
            INSERT OR IGNORE INTO broadcast_state (id, updated_at)
            VALUES (1, CURRENT_TIMESTAMP)
            """
        )
        database.execute(
            """
            UPDATE broadcast_state
            SET track_id = NULL, is_playing = 0, position_seconds = 0,
                revision = revision + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1 AND controller_id IS NULL AND is_playing = 1
            """
        )
        database.execute(
            """
            INSERT OR IGNORE INTO playlist_items (track_id, position)
            SELECT next_track_id, 0
            FROM broadcast_state
            WHERE id = 1
                AND next_track_id IS NOT NULL
                AND EXISTS (
                    SELECT 1 FROM tracks WHERE tracks.id = broadcast_state.next_track_id
                )
                AND NOT EXISTS (SELECT 1 FROM playlist_items)
            """
        )
    with connection() as database:
        violations = database.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                "The database contains broken references after schema migration."
            )

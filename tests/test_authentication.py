"""Focused tests for local DJ accounts and session handling."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config.database import connection, initialize_database
from services.authentication import (
    MAX_LOGIN_FAILURES,
    authenticate,
    approve_application,
    change_password,
    clear_login_failures,
    create_dj_application,
    create_first_admin,
    create_session,
    delete_dj_account,
    has_admin,
    list_dj_accounts,
    login_is_locked,
    list_pending_applications,
    record_login_failure,
    reject_application,
    revoke_session,
    set_dj_banned,
    user_for_session,
)


class AuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.database_path = Path(self.temporary_directory.name) / "test.sqlite3"
        self.database_patch = patch("config.database.DATABASE_PATH", self.database_path)
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)
        initialize_database()

    def test_only_one_first_administrator_can_be_created(self) -> None:
        admin = create_first_admin(
            username="station.admin",
            full_name="Station Admin",
            password="a-strong-password",
        )

        self.assertTrue(has_admin())
        self.assertEqual(admin["role"], "admin")
        self.assertIsNone(authenticate("station.admin", "wrong-password"))
        self.assertIsNotNone(authenticate("station.admin", "a-strong-password"))
        with self.assertRaisesRegex(ValueError, "already been set up"):
            create_first_admin(
                username="another.admin",
                full_name="Another Admin",
                password="another-strong-password",
            )

    def test_short_bootstrap_password_requires_change_and_admin_is_unique(self) -> None:
        admin = create_first_admin(
            username="station.admin",
            full_name="Station Admin",
            password="temp42",
        )
        self.assertTrue(admin["must_change_password"])

        with self.assertRaisesRegex(sqlite3.IntegrityError, "UNIQUE constraint failed"):
            with connection() as database:
                database.execute(
                    """
                    INSERT INTO users
                        (id, username, full_name, password_hash, role, created_at)
                    VALUES ('second-admin', 'another.admin', 'Another Admin', 'hash', 'admin', 'now')
                    """
                )

    def test_approval_issues_one_time_password_and_requires_change(self) -> None:
        application = create_dj_application(
            full_name="New DJ",
            email="new.dj@example.test",
            experience="I have hosted music programs for several years.",
        )
        admin = create_first_admin(
            username="station.admin",
            full_name="Station Admin",
            password="a-strong-password",
        )

        self.assertEqual(len(list_pending_applications()), 1)
        dj, temporary_password = approve_application(
            application_id=str(application["id"]),
            username="new.dj",
            admin_id=str(admin["id"]),
        )

        self.assertEqual(dj["role"], "dj")
        self.assertTrue(dj["must_change_password"])
        self.assertEqual(list_pending_applications(), [])
        self.assertIsNotNone(authenticate("new.dj", temporary_password))

        changed = change_password(
            user_id=str(dj["id"]),
            password="a-different-strong-password",
        )
        self.assertFalse(changed["must_change_password"])
        self.assertIsNone(authenticate("new.dj", temporary_password))
        self.assertIsNotNone(authenticate("new.dj", "a-different-strong-password"))

    def test_sessions_can_be_revoked_and_login_failures_are_throttled(self) -> None:
        admin = create_first_admin(
            username="station.admin",
            full_name="Station Admin",
            password="a-strong-password",
        )
        token, _ = create_session(str(admin["id"]))

        self.assertIsNotNone(user_for_session(token))
        revoke_session(token)
        self.assertIsNone(user_for_session(token))

        for _ in range(MAX_LOGIN_FAILURES):
            record_login_failure("station.admin")
        self.assertTrue(login_is_locked("STATION.ADMIN"))
        clear_login_failures("Station.Admin")
        self.assertFalse(login_is_locked("station.admin"))

    def test_dj_ban_revokes_sessions_and_delete_removes_only_dj_accounts(self) -> None:
        admin = create_first_admin(
            username="station.admin",
            full_name="Station Admin",
            password="a-strong-password",
        )
        application = create_dj_application(
            full_name="Managed DJ",
            email="managed.dj@example.test",
            experience="I have hosted station programs for a few years.",
        )
        dj, temporary_password = approve_application(
            application_id=str(application["id"]),
            username="managed.dj",
            admin_id=str(admin["id"]),
        )
        change_password(
            user_id=str(dj["id"]),
            password="a-different-strong-password",
        )
        token, _ = create_session(str(dj["id"]))
        self.assertIsNotNone(user_for_session(token))
        self.assertEqual(len(list_dj_accounts()), 1)

        banned = set_dj_banned(user_id=str(dj["id"]), is_banned=True)
        self.assertTrue(banned["is_banned"])
        self.assertIsNone(user_for_session(token))
        self.assertIsNone(authenticate("managed.dj", "a-different-strong-password"))
        self.assertEqual(len(list_dj_accounts()), 1)

        restored = set_dj_banned(user_id=str(dj["id"]), is_banned=False)
        self.assertFalse(restored["is_banned"])
        self.assertIsNotNone(authenticate("managed.dj", "a-different-strong-password"))
        token, _ = create_session(str(dj["id"]))

        delete_dj_account(user_id=str(dj["id"]))
        self.assertIsNone(user_for_session(token))
        self.assertIsNone(authenticate("managed.dj", "a-different-strong-password"))
        self.assertEqual(list_dj_accounts(), [])
        self.assertIsNotNone(authenticate("station.admin", "a-strong-password"))
        with self.assertRaisesRegex(ValueError, "DJ account not found"):
            delete_dj_account(user_id=str(admin["id"]))

    def test_existing_dj_accounts_migrate_as_unbanned(self) -> None:
        legacy_path = Path(self.temporary_directory.name) / "legacy-users.sqlite3"
        database = sqlite3.connect(legacy_path)
        try:
            database.execute(
                """
                CREATE TABLE users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL DEFAULT '',
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'dj')),
                    must_change_password INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            database.execute(
                """
                INSERT INTO users
                    (id, username, full_name, password_hash, role, created_at)
                VALUES ('legacy-dj', 'legacy.dj', 'Legacy DJ', 'unused', 'dj', '2026-01-01')
                """
            )
            database.commit()
        finally:
            database.close()

        with patch("config.database.DATABASE_PATH", legacy_path):
            initialize_database()
            accounts = list_dj_accounts()

        self.assertEqual(len(accounts), 1)
        self.assertFalse(accounts[0]["is_banned"])

    def test_rejected_application_is_removed_from_pending_list(self) -> None:
        application = create_dj_application(
            full_name="Applicant",
            email="applicant@example.test",
            experience="I have experience presenting a local music show.",
        )
        admin = create_first_admin(
            username="station.admin",
            full_name="Station Admin",
            password="a-strong-password",
        )

        reject_application(
            application_id=str(application["id"]),
            admin_id=str(admin["id"]),
        )
        self.assertEqual(list_pending_applications(), [])


if __name__ == "__main__":
    unittest.main()

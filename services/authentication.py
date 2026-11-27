"""Local DJ accounts, applications, and browser sessions."""

import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timezone
from uuid import uuid4

from config.database import connection

SESSION_SECONDS = 12 * 60 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
MAX_LOGIN_FAILURES = 5
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAX_MEMORY = 64 * 1024 * 1024
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,30}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_username(username: str) -> str:
    value = username.strip()
    if not _USERNAME_PATTERN.fullmatch(value):
        raise ValueError(
            "Username must be 3–30 characters using letters, numbers, dots, "
            "underscores, or hyphens."
        )
    return value


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
        maxmem=_SCRYPT_MAX_MEMORY,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


_DUMMY_PASSWORD_HASH = hash_password("invalid-login-timing-placeholder")


def _password_matches(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = encoded_hash.split("$")
        if algorithm != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=_SCRYPT_MAX_MEMORY,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def has_admin() -> bool:
    with connection() as database:
        row = database.execute(
            "SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()
    return row is not None


def public_user(user: dict[str, object]) -> dict[str, object]:
    return {
        "id": str(user["id"]),
        "username": str(user["username"]),
        "full_name": str(user["full_name"]),
        "role": str(user["role"]),
        "must_change_password": bool(user["must_change_password"]),
    }


def list_dj_accounts() -> list[dict[str, object]]:
    with connection() as database:
        rows = database.execute(
            """
            SELECT id, username, full_name, email, is_banned, created_at
            FROM users
            WHERE role = 'dj'
            ORDER BY full_name COLLATE NOCASE, username COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def set_dj_banned(*, user_id: str, is_banned: bool) -> dict[str, object]:
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        user = database.execute(
            "SELECT id, username FROM users WHERE id = ? AND role = 'dj'",
            (user_id,),
        ).fetchone()
        if user is None:
            raise ValueError("DJ account not found.")
        database.execute(
            "UPDATE users SET is_banned = ? WHERE id = ? AND role = 'dj'",
            (int(is_banned), user_id),
        )
        if is_banned:
            database.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        database.execute(
            "DELETE FROM auth_login_attempts WHERE username = ? COLLATE NOCASE",
            (user["username"],),
        )
        updated = database.execute(
            """
            SELECT id, username, full_name, email, is_banned, created_at
            FROM users WHERE id = ? AND role = 'dj'
            """,
            (user_id,),
        ).fetchone()
    if updated is None:
        raise RuntimeError("The DJ account status was not updated.")
    return dict(updated)


def delete_dj_account(*, user_id: str) -> None:
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        user = database.execute(
            "SELECT username FROM users WHERE id = ? AND role = 'dj'",
            (user_id,),
        ).fetchone()
        if user is None:
            raise ValueError("DJ account not found.")
        database.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        database.execute(
            "DELETE FROM auth_login_attempts WHERE username = ? COLLATE NOCASE",
            (user["username"],),
        )
        database.execute(
            "DELETE FROM users WHERE id = ? AND role = 'dj'",
            (user_id,),
        )


def create_first_admin(
    *, username: str, full_name: str, password: str
) -> dict[str, object]:
    clean_username = normalize_username(username)
    clean_name = full_name.strip()
    if not 2 <= len(clean_name) <= 100:
        raise ValueError("Administrator name must be between 2 and 100 characters.")
    if len(password) < 6:
        raise ValueError("Temporary administrator password must be at least 6 characters.")

    user_id = uuid4().hex
    now = _now_iso()
    password_digest = hash_password(password)
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        exists = database.execute(
            "SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()
        if exists is not None:
            raise ValueError("The station administrator has already been set up.")
        database.execute(
            """
            INSERT INTO users
                (id, username, full_name, password_hash, role,
                 must_change_password, created_at)
            VALUES (?, ?, ?, ?, 'admin', ?, ?)
            """,
            (
                user_id,
                clean_username,
                clean_name,
                password_digest,
                int(len(password) < 12),
                now,
            ),
        )
        row = database.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise RuntimeError("The administrator account was not created.")
    return dict(row)


def create_dj_application(
    *, full_name: str, email: str, experience: str
) -> dict[str, object]:
    clean_name = full_name.strip()
    clean_email = email.strip().lower()
    clean_experience = experience.strip()
    if not 2 <= len(clean_name) <= 100:
        raise ValueError("Name must be between 2 and 100 characters.")
    if not 5 <= len(clean_email) <= 254 or not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", clean_email
    ):
        raise ValueError("Enter a valid email address.")
    if not 10 <= len(clean_experience) <= 1000:
        raise ValueError("Tell the admin a little about your DJ experience (10–1000 characters).")

    application_id = uuid4().hex
    with connection() as database:
        database.execute(
            """
            INSERT INTO dj_applications
                (id, full_name, email, experience, submitted_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (application_id, clean_name, clean_email, clean_experience, _now_iso()),
        )
        row = database.execute(
            "SELECT * FROM dj_applications WHERE id = ?", (application_id,)
        ).fetchone()
    if row is None:
        raise RuntimeError("The DJ application was not saved.")
    return dict(row)


def list_pending_applications() -> list[dict[str, object]]:
    with connection() as database:
        rows = database.execute(
            """
            SELECT id, full_name, email, experience, submitted_at
            FROM dj_applications
            WHERE status = 'pending'
            ORDER BY submitted_at ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def approve_application(
    *, application_id: str, username: str, admin_id: str
) -> tuple[dict[str, object], str]:
    clean_username = normalize_username(username)
    temporary_password = secrets.token_urlsafe(12)
    password_digest = hash_password(temporary_password)
    user_id = uuid4().hex
    now = _now_iso()
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        application = database.execute(
            "SELECT * FROM dj_applications WHERE id = ? AND status = 'pending'",
            (application_id,),
        ).fetchone()
        if application is None:
            raise ValueError("Pending DJ application not found.")
        database.execute(
            """
            INSERT INTO users
                (id, username, full_name, email, password_hash, role,
                 must_change_password, created_at)
            VALUES (?, ?, ?, ?, ?, 'dj', 1, ?)
            """,
            (
                user_id,
                clean_username,
                application["full_name"],
                application["email"],
                password_digest,
                now,
            ),
        )
        database.execute(
            """
            UPDATE dj_applications
            SET status = 'approved', assigned_username = ?, reviewed_at = ?,
                reviewed_by = ?
            WHERE id = ?
            """,
            (clean_username, now, admin_id, application_id),
        )
        user = database.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        raise RuntimeError("The approved DJ account was not created.")
    return dict(user), temporary_password


def reject_application(*, application_id: str, admin_id: str) -> None:
    with connection() as database:
        cursor = database.execute(
            """
            UPDATE dj_applications
            SET status = 'rejected', reviewed_at = ?, reviewed_by = ?
            WHERE id = ? AND status = 'pending'
            """,
            (_now_iso(), admin_id, application_id),
        )
    if cursor.rowcount == 0:
        raise ValueError("Pending DJ application not found.")


def authenticate(username: str, password: str) -> dict[str, object] | None:
    with connection() as database:
        row = database.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
    if row is None:
        _password_matches(password, _DUMMY_PASSWORD_HASH)
        return None
    user = dict(row)
    password_matches = _password_matches(password, str(user["password_hash"]))
    return user if password_matches and not bool(user["is_banned"]) else None


def create_session(user_id: str) -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + SESSION_SECONDS
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connection() as database:
        database.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (int(time.time()),))
        database.execute(
            "INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, user_id, expires_at),
        )
    return token, expires_at


def user_for_session(token: str) -> dict[str, object] | None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connection() as database:
        row = database.execute(
            """
            SELECT users.*
            FROM auth_sessions
            JOIN users ON users.id = auth_sessions.user_id
            WHERE auth_sessions.token_hash = ?
                AND auth_sessions.expires_at > ?
                AND users.is_banned = 0
            """,
            (token_hash, int(time.time())),
        ).fetchone()
    return dict(row) if row is not None else None


def revoke_session(token: str) -> None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connection() as database:
        database.execute(
            "DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,)
        )


def change_password(*, user_id: str, password: str) -> dict[str, object]:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters.")
    with connection() as database:
        database.execute(
            """
            UPDATE users
            SET password_hash = ?, must_change_password = 0
            WHERE id = ?
            """,
            (hash_password(password), user_id),
        )
        row = database.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise ValueError("DJ account not found.")
    return dict(row)


def login_is_locked(username: str) -> bool:
    with connection() as database:
        row = database.execute(
            "SELECT locked_until FROM auth_login_attempts WHERE username = ?",
            (username.strip().casefold(),),
        ).fetchone()
    return row is not None and int(row["locked_until"]) > int(time.time())


def record_login_failure(username: str) -> None:
    normalized = username.strip().casefold()
    if not normalized:
        return
    now = int(time.time())
    with connection() as database:
        row = database.execute(
            "SELECT * FROM auth_login_attempts WHERE username = ?", (normalized,)
        ).fetchone()
        if row is None or now - int(row["window_started_at"]) >= LOGIN_WINDOW_SECONDS:
            failed_attempts = 1
            window_started_at = now
        else:
            failed_attempts = int(row["failed_attempts"]) + 1
            window_started_at = int(row["window_started_at"])
        locked_until = (
            now + LOGIN_WINDOW_SECONDS
            if failed_attempts >= MAX_LOGIN_FAILURES
            else 0
        )
        database.execute(
            """
            INSERT INTO auth_login_attempts
                (username, failed_attempts, window_started_at, locked_until)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                failed_attempts = excluded.failed_attempts,
                window_started_at = excluded.window_started_at,
                locked_until = excluded.locked_until
            """,
            (normalized, failed_attempts, window_started_at, locked_until),
        )


def clear_login_failures(username: str) -> None:
    with connection() as database:
        database.execute(
            "DELETE FROM auth_login_attempts WHERE username = ?",
            (username.strip().casefold(),),
        )

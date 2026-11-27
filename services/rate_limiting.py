"""Persistent per-client limits for public HTTP endpoints."""

import hashlib
import time

from config.database import connection


def check_rate_limit(
    *,
    scope: str,
    client_address: str,
    max_requests: int,
    window_seconds: int,
) -> int | None:
    if not scope or not client_address:
        raise ValueError("A rate-limit scope and client address are required.")
    if max_requests < 1 or window_seconds < 1:
        raise ValueError("Rate limits must have positive request and window limits.")

    now = int(time.time())
    client_hash = hashlib.sha256(client_address.encode("utf-8")).hexdigest()
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        database.execute(
            "DELETE FROM public_rate_limits WHERE window_started_at < ?",
            (now - 24 * 60 * 60,),
        )
        row = database.execute(
            """
            SELECT window_started_at, request_count
            FROM public_rate_limits
            WHERE scope = ? AND client_hash = ?
            """,
            (scope, client_hash),
        ).fetchone()
        if row is None or now >= int(row["window_started_at"]) + window_seconds:
            database.execute(
                """
                INSERT INTO public_rate_limits
                    (scope, client_hash, window_started_at, request_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(scope, client_hash) DO UPDATE SET
                    window_started_at = excluded.window_started_at,
                    request_count = 1
                """,
                (scope, client_hash, now),
            )
            return None

        if int(row["request_count"]) >= max_requests:
            return max(1, int(row["window_started_at"]) + window_seconds - now)

        database.execute(
            """
            UPDATE public_rate_limits
            SET request_count = request_count + 1
            WHERE scope = ? AND client_hash = ?
            """,
            (scope, client_hash),
        )
    return None

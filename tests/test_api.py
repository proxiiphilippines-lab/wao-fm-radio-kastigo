"""HTTP integration tests for critical authentication and media routes."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import SESSION_COOKIE, app, set_session_cookie
from config.database import connection, initialize_database
from services.authentication import create_first_admin, create_session
from services.broadcast import claim_control, current_state
from services.music_library import get_track, register_track
from starlette.requests import Request
from starlette.responses import Response


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.database_path = root / "test.sqlite3"
        self.media_dir = root / "music"
        self.ads_dir = root / "ads"

        patches = (
            patch("config.database.DATABASE_PATH", self.database_path),
            patch("api.main.MUSIC_DIR", self.media_dir),
            patch("api.main.ADS_DIR", self.ads_dir),
            patch("api.main.APP_ENV", "development"),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        self.client = TestClient(app, raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def _create_track(self, name: str = "track.mp3") -> tuple[dict[str, object], Path]:
        self.media_dir.mkdir(parents=True, exist_ok=True)
        path = self.media_dir / name
        path.write_bytes(b"test audio")
        track = register_track(
            title=Path(name).stem,
            artist="Station",
            file_name=name,
            file_path=path,
            content_type="audio/mpeg",
            size_bytes=path.stat().st_size,
        )
        return track, path

    def _sign_in_admin(self) -> None:
        admin = create_first_admin(
            username="station.admin",
            full_name="Station Admin",
            password="a-strong-password",
        )
        token, _ = create_session(str(admin["id"]))
        self.client.cookies.set(SESSION_COOKIE, token, path="/")

    def test_production_bootstrap_requires_configured_setup_token(self) -> None:
        with (
            patch("api.main.APP_ENV", "production"),
            patch("api.main.BOOTSTRAP_TOKEN", "one-time-setup-secret"),
        ):
            status = self.client.get("/api/auth/status").json()
            self.assertTrue(status["bootstrap_available"])
            self.assertTrue(status["bootstrap_token_required"])

            rejected = self.client.post(
                "/api/auth/bootstrap",
                json={
                    "username": "station.admin",
                    "full_name": "Station Admin",
                    "password": "a-strong-password",
                },
            )
            self.assertEqual(rejected.status_code, 403)

            created = self.client.post(
                "/api/auth/bootstrap",
                json={
                    "username": "station.admin",
                    "full_name": "Station Admin",
                    "password": "a-strong-password",
                    "setup_token": "one-time-setup-secret",
                },
            )
            self.assertEqual(created.status_code, 201)
            self.assertIn("secure", created.headers["set-cookie"].lower())

    def test_render_origin_is_allowed_for_credentialed_cors(self) -> None:
        response = self.client.options(
            "/api/auth/status",
            headers={
                "Origin": "https://kastigo.onrender.com",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"],
            "https://kastigo.onrender.com",
        )
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")

    def test_https_session_cookie_supports_cross_site_frontend(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "scheme": "https",
                "server": ("api.example.test", 443),
                "client": ("127.0.0.1", 12345),
                "path": "/api/auth/login",
                "query_string": b"",
                "headers": [],
            }
        )
        response = Response()

        set_session_cookie(response, request, "test-session-token")

        cookie = response.headers["set-cookie"].lower()
        self.assertIn("secure", cookie)
        self.assertIn("samesite=none", cookie)

    def test_production_bootstrap_is_unavailable_without_a_server_token(self) -> None:
        with (
            patch("api.main.APP_ENV", "production"),
            patch("api.main.BOOTSTRAP_TOKEN", ""),
        ):
            status = self.client.get("/api/auth/status").json()
            self.assertFalse(status["bootstrap_available"])

            response = self.client.post(
                "/api/auth/bootstrap",
                json={
                    "username": "station.admin",
                    "full_name": "Station Admin",
                    "password": "a-strong-password",
                },
            )
            self.assertEqual(response.status_code, 503)

    def test_guest_stream_of_off_air_track_returns_forbidden(self) -> None:
        track, _ = self._create_track()

        response = self.client.get(f"/api/tracks/{track['id']}/stream")

        self.assertEqual(response.status_code, 403)

    def test_public_dj_applications_are_rate_limited_per_client(self) -> None:
        for index in range(5):
            response = self.client.post(
                "/api/auth/applications",
                json={
                    "full_name": f"Applicant {index}",
                    "email": f"applicant{index}@example.test",
                    "experience": "I have hosted local music programs for years.",
                },
            )
            self.assertEqual(response.status_code, 201)

        limited = self.client.post(
            "/api/auth/applications",
            json={
                "full_name": "Applicant Extra",
                "email": "applicant-extra@example.test",
                "experience": "I have hosted local music programs for years.",
            },
        )

        self.assertEqual(limited.status_code, 429)
        self.assertGreater(int(limited.headers["retry-after"]), 0)

    def test_track_delete_commits_before_removing_audio_file(self) -> None:
        track, path = self._create_track()
        self._sign_in_admin()
        claim_control(controller_id="admin-tab", track_id=str(track["id"]))

        response = self.client.delete(f"/api/tracks/{track['id']}")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(path.exists())
        self.assertIsNone(get_track(str(track["id"])))
        self.assertIsNone(current_state()["track"])
        self.assertFalse(current_state()["is_playing"])

    def test_failed_track_delete_preserves_audio_and_live_state(self) -> None:
        track, path = self._create_track()
        self._sign_in_admin()
        claim_control(controller_id="admin-tab", track_id=str(track["id"]))
        with connection() as database:
            database.execute(
                """
                CREATE TRIGGER reject_track_delete
                BEFORE DELETE ON tracks
                BEGIN
                    SELECT RAISE(ABORT, 'delete blocked for test');
                END
                """
            )

        response = self.client.delete(f"/api/tracks/{track['id']}")

        self.assertEqual(response.status_code, 500)
        self.assertTrue(path.is_file())
        self.assertIsNotNone(get_track(str(track["id"])))
        self.assertEqual(current_state()["track"]["id"], track["id"])
        self.assertTrue(current_state()["is_playing"])


if __name__ == "__main__":
    unittest.main()

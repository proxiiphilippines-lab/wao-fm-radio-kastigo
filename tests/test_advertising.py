"""Focused tests for advertiser request intake and review."""

from io import BytesIO
import tempfile
import unittest
from pathlib import Path
import sqlite3
from unittest.mock import patch

from PIL import Image

from config.database import initialize_database
from services.advertising import (
    create_ad_application,
    clear_live_ad,
    get_live_ad,
    list_pending_ad_applications,
    live_ad_image,
    mark_ad_application_reviewed,
    update_live_ad,
)


class AdvertisingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        database_path = Path(self.temporary_directory.name) / "test.sqlite3"
        self.database_patch = patch("config.database.DATABASE_PATH", database_path)
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)
        self.ads_patch = patch(
            "services.advertising.ADS_DIR",
            Path(self.temporary_directory.name) / "ads",
        )
        self.ads_patch.start()
        self.addCleanup(self.ads_patch.stop)
        initialize_database()

    @staticmethod
    def _image_bytes(image_format: str, mode: str = "RGB") -> bytes:
        image = Image.new(mode, (8, 6), (30, 120, 210, 128) if mode == "RGBA" else (30, 120, 210))
        output = BytesIO()
        image.save(output, format=image_format)
        return output.getvalue()

    def test_request_is_saved_then_removed_from_pending_after_review(self) -> None:
        application = create_ad_application(
            contact_name="  Alex Santos ",
            business_name=" Kape Corner ",
            email=" ADS@EXAMPLE.TEST ",
            phone=" 555-0123 ",
            ad_details="Please promote our weekend coffee sale.",
        )

        self.assertEqual(application["contact_name"], "Alex Santos")
        self.assertEqual(application["business_name"], "Kape Corner")
        self.assertEqual(application["email"], "ads@example.test")
        self.assertEqual(len(list_pending_ad_applications()), 1)

        mark_ad_application_reviewed(str(application["id"]))
        self.assertEqual(list_pending_ad_applications(), [])
        with self.assertRaisesRegex(ValueError, "not found"):
            mark_ad_application_reviewed(str(application["id"]))

    def test_request_rejects_invalid_contact_or_campaign_details(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid email"):
            create_ad_application(
                contact_name="Alex Santos",
                business_name="",
                email="invalid",
                phone="",
                ad_details="Promote our event this weekend.",
            )

        with self.assertRaisesRegex(ValueError, "Ad details"):
            create_ad_application(
                contact_name="Alex Santos",
                business_name="",
                email="alex@example.test",
                phone="",
                ad_details="short",
            )

    def test_live_ad_publishes_text_and_image_and_can_be_cleared(self) -> None:
        image_bytes = self._image_bytes("PNG")
        second_image = self._image_bytes("JPEG")
        published = update_live_ad(
            text="  Weekend sale today!  ",
            image_uploads=[image_bytes, second_image],
        )

        self.assertEqual(published["text"], "Weekend sale today!")
        self.assertEqual(len(published["images"]), 2)
        self.assertTrue(
            str(published["images"][0]["url"]).startswith(
                "/api/public/live-ad/images/"
            )
        )
        image = live_ad_image(str(published["images"][0]["id"]))
        self.assertIsNotNone(image)
        self.assertEqual(image[1], "image/jpeg")
        with Image.open(image[0]) as stored_image:
            self.assertEqual(stored_image.format, "JPEG")

        text_only_update = update_live_ad(text="New scrolling message")
        self.assertEqual(text_only_update["text"], "New scrolling message")
        self.assertEqual(text_only_update["images"], published["images"])

        clear_live_ad()
        self.assertEqual(get_live_ad(), {"text": "", "images": [], "updated_at": None})
        self.assertIsNone(live_ad_image())

    def test_live_ad_rejects_non_image_data_without_publishing(self) -> None:
        with self.assertRaisesRegex(ValueError, "supported or readable photo"):
            update_live_ad(
                text="Invalid image",
                image_uploads=[b"not an image"],
            )

        self.assertEqual(get_live_ad(), {"text": "", "images": [], "updated_at": None})

    def test_live_ad_normalizes_common_photo_formats_for_browser_display(self) -> None:
        for image_format in ("AVIF", "BMP", "GIF", "HEIF", "TIFF", "WEBP"):
            with self.subTest(image_format=image_format):
                published = update_live_ad(
                    text="Format test",
                    image_uploads=[self._image_bytes(image_format)],
                )
                stored_image = live_ad_image(str(published["images"][0]["id"]))
                self.assertIsNotNone(stored_image)
                self.assertEqual(stored_image[1], "image/jpeg")
                with Image.open(stored_image[0]) as decoded:
                    self.assertEqual(decoded.format, "JPEG")

    def test_live_ad_preserves_transparency_when_normalizing(self) -> None:
        published = update_live_ad(
            text="Transparent banner",
            image_uploads=[self._image_bytes("PNG", "RGBA")],
        )
        stored_image = live_ad_image(str(published["images"][0]["id"]))

        self.assertIsNotNone(stored_image)
        self.assertEqual(stored_image[1], "image/png")
        with Image.open(stored_image[0]) as decoded:
            self.assertEqual(decoded.mode, "RGBA")

    def test_live_ad_rejects_more_than_fifty_images(self) -> None:
        with self.assertRaisesRegex(ValueError, "no more than 50"):
            update_live_ad(
                text="Too many banners",
                image_uploads=[b"image"] * 51,
            )

        self.assertEqual(get_live_ad()["images"], [])

    def test_live_ad_accepts_fifty_images(self) -> None:
        image_uploads = [self._image_bytes("JPEG")] * 50
        published = update_live_ad(text="Full campaign", image_uploads=image_uploads)

        self.assertEqual(len(published["images"]), 50)
        self.assertEqual(
            [live_ad_image(image["id"])[1] for image in published["images"]],
            ["image/jpeg"] * 50,
        )

    def test_live_ad_can_append_images_to_existing_slideshow(self) -> None:
        initial = update_live_ad(
            text="Campaign",
            image_uploads=[self._image_bytes("JPEG"), self._image_bytes("PNG")],
        )

        appended_image = self._image_bytes("BMP")
        updated = update_live_ad(
            text="Campaign extended",
            image_uploads=[appended_image],
            append_images=True,
        )

        self.assertEqual(len(updated["images"]), 3)
        self.assertEqual(
            [image["id"] for image in updated["images"][:2]],
            [image["id"] for image in initial["images"]],
        )
        appended = live_ad_image(str(updated["images"][2]["id"]))
        self.assertEqual(appended[1], "image/jpeg")
        with Image.open(appended[0]) as stored:
            self.assertEqual(stored.format, "JPEG")

    def test_live_ad_append_respects_total_fifty_image_limit(self) -> None:
        initial = update_live_ad(
            text="Full slideshow",
            image_uploads=[self._image_bytes("JPEG")] * 50,
        )

        with self.assertRaisesRegex(ValueError, "no more than 50"):
            update_live_ad(
                text="One too many",
                image_uploads=[self._image_bytes("JPEG")],
                append_images=True,
            )

        self.assertEqual(get_live_ad()["images"], initial["images"])

    def test_initialize_database_migrates_existing_single_live_ad_image(self) -> None:
        database_path = Path(self.temporary_directory.name) / "legacy.sqlite3"
        image_directory = Path(self.temporary_directory.name) / "legacy-ads"
        image_directory.mkdir()
        image_bytes = b"\x89PNG\r\n\x1a\nlegacy-ad"
        (image_directory / "legacy.png").write_bytes(image_bytes)
        database = sqlite3.connect(database_path)
        try:
            database.execute(
                """
                CREATE TABLE live_ad (
                    id INTEGER PRIMARY KEY,
                    text TEXT NOT NULL DEFAULT '',
                    image_filename TEXT,
                    image_content_type TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            database.execute(
                """
                INSERT INTO live_ad
                    (id, text, image_filename, image_content_type, updated_at)
                VALUES (1, 'Existing campaign', 'legacy.png', 'image/png', '2026-01-01')
                """
            )
            database.commit()
        finally:
            database.close()

        with (
            patch("config.database.DATABASE_PATH", database_path),
            patch("services.advertising.ADS_DIR", image_directory),
        ):
            initialize_database()
            ad = get_live_ad()
            self.assertEqual(ad["text"], "Existing campaign")
            self.assertEqual(len(ad["images"]), 1)
            image = live_ad_image(str(ad["images"][0]["id"]))

        self.assertIsNotNone(image)
        self.assertEqual(image[0].read_bytes(), image_bytes)


if __name__ == "__main__":
    unittest.main()

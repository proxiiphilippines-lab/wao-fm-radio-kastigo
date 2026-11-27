"""Local advertising request intake and review operations."""

from io import BytesIO
import re
import sqlite3
import warnings
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from config.database import connection
from config.settings import (
    ADS_DIR,
    MAX_AD_IMAGE_BYTES,
    MAX_AD_IMAGE_COUNT,
    MAX_AD_IMAGE_PIXELS,
)

register_heif_opener()

_SUPPORTED_AD_IMAGE_FORMATS = {
    "AVIF",
    "BMP",
    "GIF",
    "HEIF",
    "JPEG",
    "PNG",
    "TIFF",
    "WEBP",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_ad_application(
    *,
    contact_name: str,
    business_name: str,
    email: str,
    phone: str,
    ad_details: str,
) -> dict[str, object]:
    clean_contact = contact_name.strip()
    clean_business = business_name.strip()
    clean_email = email.strip().lower()
    clean_phone = phone.strip()
    clean_details = ad_details.strip()

    if not 2 <= len(clean_contact) <= 100:
        raise ValueError("Contact name must be between 2 and 100 characters.")
    if len(clean_business) > 100:
        raise ValueError("Business name must be at most 100 characters.")
    if not 5 <= len(clean_email) <= 254 or not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", clean_email
    ):
        raise ValueError("Enter a valid email address.")
    if len(clean_phone) > 30:
        raise ValueError("Phone number must be at most 30 characters.")
    if not 10 <= len(clean_details) <= 1000:
        raise ValueError("Ad details must be between 10 and 1000 characters.")

    application_id = uuid4().hex
    submitted_at = _now_iso()
    with connection() as database:
        database.execute(
            """
            INSERT INTO ad_applications
                (id, contact_name, business_name, email, phone, ad_details, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                clean_contact,
                clean_business,
                clean_email,
                clean_phone,
                clean_details,
                submitted_at,
            ),
        )
        row = database.execute(
            """
            SELECT id, contact_name, business_name, email, phone, ad_details, submitted_at
            FROM ad_applications
            WHERE id = ?
            """,
            (application_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("The advertising request was not saved.")
    return dict(row)


def list_pending_ad_applications() -> list[dict[str, object]]:
    with connection() as database:
        rows = database.execute(
            """
            SELECT id, contact_name, business_name, email, phone, ad_details, submitted_at
            FROM ad_applications
            WHERE status = 'pending'
            ORDER BY submitted_at ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def mark_ad_application_reviewed(application_id: str) -> None:
    with connection() as database:
        cursor = database.execute(
            """
            UPDATE ad_applications
            SET status = 'reviewed', reviewed_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (_now_iso(), application_id),
        )
    if cursor.rowcount == 0:
        raise ValueError("Pending advertising request not found.")


def _normalize_ad_image(data: bytes) -> tuple[bytes, str, str]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in _SUPPORTED_AD_IMAGE_FORMATS:
                    raise ValueError(
                        "Upload a JPG, PNG, WebP, GIF, BMP, TIFF, HEIC, HEIF, or AVIF image."
                    )
                if source.width * source.height > MAX_AD_IMAGE_PIXELS:
                    raise ValueError("Advertisement images cannot exceed 40 megapixels.")
                image = ImageOps.exif_transpose(source)
                has_alpha = "A" in image.getbands() or "transparency" in image.info
                image.thumbnail((3000, 3000), Image.Resampling.LANCZOS)

                if has_alpha:
                    output = BytesIO()
                    image.convert("RGBA").save(output, format="PNG", optimize=True)
                    if output.tell() <= MAX_AD_IMAGE_BYTES:
                        return output.getvalue(), ".png", "image/png"
                    rgba = image.convert("RGBA")
                    background = Image.new("RGBA", rgba.size, "white")
                    image = Image.alpha_composite(background, rgba).convert("RGB")
                else:
                    image = image.convert("RGB")

                for quality in (88, 80, 72, 64):
                    output = BytesIO()
                    image.save(
                        output,
                        format="JPEG",
                        quality=quality,
                        optimize=True,
                    )
                    if output.tell() <= MAX_AD_IMAGE_BYTES:
                        return output.getvalue(), ".jpg", "image/jpeg"
                raise ValueError(
                    "This image could not be reduced below the 5 MB storage limit."
                )
    except ValueError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
    ) as error:
        raise ValueError(
            "The selected file is not a supported or readable photo."
        ) from error


def _ad_image_path(filename: str) -> Path:
    if Path(filename).name != filename:
        raise RuntimeError("The live advertisement image path is invalid.")
    return ADS_DIR / filename


def _public_live_ad(
    row: sqlite3.Row | None, images: list[sqlite3.Row]
) -> dict[str, object]:
    if row is None:
        return {"text": "", "images": [], "updated_at": None}
    return {
        "text": row["text"],
        "images": [
            {
                "id": image["id"],
                "url": (
                    f"/api/public/live-ad/images/{quote(str(image['id']), safe='')}"
                    f"?v={quote(str(image['filename']), safe='')}"
                ),
            }
            for image in images
        ],
        "updated_at": row["updated_at"],
    }


def _live_ad_images(database: sqlite3.Connection) -> list[sqlite3.Row]:
    return database.execute(
        """
        SELECT id, filename, content_type
        FROM live_ad_images
        WHERE ad_id = 1
        ORDER BY sort_order ASC
        """
    ).fetchall()


def get_live_ad() -> dict[str, object]:
    with connection() as database:
        row = database.execute(
            """
            SELECT text, updated_at
            FROM live_ad
            WHERE id = 1
            """
        ).fetchone()
        images = _live_ad_images(database)
    return _public_live_ad(row, images)


def live_ad_image(image_id: str | None = None) -> tuple[Path, str] | None:
    with connection() as database:
        if image_id is None:
            row = database.execute(
                """
                SELECT filename, content_type
                FROM live_ad_images
                WHERE ad_id = 1
                ORDER BY sort_order ASC
                LIMIT 1
                """
            ).fetchone()
        else:
            row = database.execute(
                """
                SELECT filename, content_type
                FROM live_ad_images
                WHERE ad_id = 1 AND id = ?
                """,
                (image_id,),
            ).fetchone()
    if row is None:
        return None

    image_path = _ad_image_path(str(row["filename"]))
    if not image_path.is_file():
        raise FileNotFoundError("The live advertisement image is missing.")
    return image_path, str(row["content_type"])


def update_live_ad(
    *,
    text: str,
    image_uploads: list[bytes] | None = None,
    remove_images: bool = False,
    append_images: bool = False,
) -> dict[str, object]:
    clean_text = text.strip()
    if len(clean_text) > 1000:
        raise ValueError("Advertisement text must be at most 1000 characters.")

    if image_uploads is not None and len(image_uploads) > MAX_AD_IMAGE_COUNT:
        raise ValueError(f"Upload no more than {MAX_AD_IMAGE_COUNT} advertisement images.")
    if remove_images and (image_uploads or append_images):
        raise ValueError("Upload new images or remove the current images, not both.")

    prepared_images: list[tuple[str, str, str, bytes]] = []
    for image_data in image_uploads or []:
        if not image_data:
            raise ValueError("The selected advertisement image is empty.")
        if len(image_data) > MAX_AD_IMAGE_BYTES:
            raise ValueError("Advertisement images cannot exceed 5 MB.")
        image_data, image_extension, image_content_type = _normalize_ad_image(image_data)
        image_id = f"{uuid4().hex}{image_extension}"
        prepared_images.append((image_id, image_id, image_content_type, image_data))

    with connection() as database:
        old_images = _live_ad_images(database)
        legacy = database.execute(
            "SELECT image_filename FROM live_ad WHERE id = 1"
        ).fetchone()

    retained_old_images = old_images if append_images else []
    if len(retained_old_images) + len(prepared_images) > MAX_AD_IMAGE_COUNT:
        raise ValueError(
            f"The slideshow can contain no more than {MAX_AD_IMAGE_COUNT} advertisement images."
        )

    for image in old_images:
        _ad_image_path(str(image["filename"]))
    legacy_filename = (
        str(legacy["image_filename"])
        if legacy is not None and legacy["image_filename"]
        else None
    )
    if legacy_filename:
        _ad_image_path(legacy_filename)

    created_paths: list[Path] = []
    saved = False
    try:
        if prepared_images:
            ADS_DIR.mkdir(parents=True, exist_ok=True)
            for _, filename, _, image_data in prepared_images:
                image_path = _ad_image_path(filename)
                created_paths.append(image_path)
                image_path.write_bytes(image_data)

        if prepared_images:
            retained_images = [
                *[
                    (str(image["id"]), str(image["filename"]), str(image["content_type"]))
                    for image in retained_old_images
                ],
                *[
                    (image_id, filename, content_type)
                    for image_id, filename, content_type, _ in prepared_images
                ],
            ]
        elif remove_images:
            retained_images = []
        else:
            retained_images = [
                (str(image["id"]), str(image["filename"]), str(image["content_type"]))
                for image in old_images
            ]

        updated_at = _now_iso()
        with connection() as database:
            database.execute(
                """
                INSERT INTO live_ad
                    (id, text, image_filename, image_content_type, updated_at)
                VALUES (1, ?, NULL, NULL, ?)
                ON CONFLICT(id) DO UPDATE SET
                    text = excluded.text,
                    updated_at = excluded.updated_at
                """,
                (clean_text, updated_at),
            )
            database.execute(
                "DELETE FROM live_ad_images WHERE ad_id = 1"
            )
            database.executemany(
                """
                INSERT INTO live_ad_images
                    (id, filename, content_type, sort_order, created_at, ad_id)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                [
                    (image_id, filename, content_type, index, updated_at)
                    for index, (image_id, filename, content_type) in enumerate(retained_images)
                ],
            )
            row = database.execute(
                """
                SELECT text, updated_at
                FROM live_ad
                WHERE id = 1
                """
            ).fetchone()
        saved = True
    finally:
        if not saved:
            for created_path in created_paths:
                created_path.unlink(missing_ok=True)

    retained_filenames = {filename for _, filename, _ in retained_images}
    old_filenames = {str(image["filename"]) for image in old_images}
    if legacy_filename:
        old_filenames.add(legacy_filename)
    for filename in old_filenames - retained_filenames:
        _ad_image_path(filename).unlink(missing_ok=True)

    with connection() as database:
        images = _live_ad_images(database)
    return _public_live_ad(row, images)


def clear_live_ad() -> None:
    with connection() as database:
        images = _live_ad_images(database)
        legacy = database.execute(
            "SELECT image_filename FROM live_ad WHERE id = 1"
        ).fetchone()
        filenames = {str(image["filename"]) for image in images}
        if legacy is not None and legacy["image_filename"]:
            filenames.add(str(legacy["image_filename"]))
        for filename in filenames:
            _ad_image_path(filename)
        database.execute("DELETE FROM live_ad WHERE id = 1")
    for filename in filenames:
        _ad_image_path(filename).unlink(missing_ok=True)

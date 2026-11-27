"""Local paths and limits for the KASTIGO application."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
MUSIC_DIR = DATA_DIR / "music"
ADS_DIR = DATA_DIR / "ads"
DATABASE_PATH = DATA_DIR / "kastigo.sqlite3"
UI_DIST_DIR = PROJECT_ROOT / "ui" / "dist"

APP_ENV = os.environ.get("KASTIGO_ENV", "development").strip().lower()
if APP_ENV not in {"development", "production"}:
    raise ValueError("KASTIGO_ENV must be 'development' or 'production'.")

BOOTSTRAP_TOKEN = os.environ.get("KASTIGO_BOOTSTRAP_TOKEN", "").strip()
if APP_ENV == "production" and BOOTSTRAP_TOKEN and len(BOOTSTRAP_TOKEN) < 32:
    raise ValueError("Production bootstrap tokens must be at least 32 characters long.")
SERVER_HOST = os.environ.get("KASTIGO_HOST", "127.0.0.1").strip()
try:
    SERVER_PORT = int(os.environ.get("KASTIGO_PORT", "8000"))
except ValueError as error:
    raise ValueError("KASTIGO_PORT must be a valid TCP port.") from error
if not SERVER_HOST or not 1 <= SERVER_PORT <= 65535:
    raise ValueError("KASTIGO_HOST and KASTIGO_PORT must be valid server settings.")
CORS_ALLOWED_ORIGINS = tuple(
    origin.strip()
    for origin in os.environ.get(
        "KASTIGO_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
)
CORS_ALLOWED_ORIGIN_REGEX = r"^https://[a-z0-9-]+\.onrender\.com$"

MAX_UPLOAD_BYTES = 250 * 1024 * 1024
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}
MAX_AD_IMAGE_BYTES = 5 * 1024 * 1024
MAX_AD_IMAGE_COUNT = 50
MAX_AD_IMAGE_PIXELS = 40_000_000

"""FastAPI application for the local KASTIGO web client."""

from contextlib import asynccontextmanager
import hmac
import logging
import mimetypes
from pathlib import Path
import sqlite3
from typing import Annotated, AsyncGenerator, Literal, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config.database import initialize_database
from config.settings import (
    ADS_DIR,
    APP_ENV,
    ALLOWED_AUDIO_EXTENSIONS,
    BOOTSTRAP_TOKEN,
    MAX_AD_IMAGE_COUNT,
    MAX_AD_IMAGE_BYTES,
    MAX_UPLOAD_BYTES,
    MUSIC_DIR,
    UI_DIST_DIR,
)
from services import (
    advertising,
    authentication,
    broadcast,
    monitoring,
    music_library,
    playlist,
    rate_limiting,
)

SESSION_COOKIE = "kastigo_session"
LOGGER = logging.getLogger(__name__)


class TrackResponse(BaseModel):
    id: str
    title: str
    artist: str
    file_name: str
    content_type: str
    category: str
    duration_seconds: float | None
    size_bytes: int
    created_at: str
    stream_url: str


class MonitorEventCreate(BaseModel):
    event_type: Literal[
        "playback_started", "playback_paused", "playback_ended", "playback_error"
    ]
    message: str = Field(min_length=1, max_length=300)
    track_id: str | None = None


class MonitorEventResponse(BaseModel):
    id: int
    event_type: str
    message: str
    track_id: str | None
    track_title: str | None = None
    created_at: str


class UserResponse(BaseModel):
    id: str
    username: str
    full_name: str
    role: Literal["admin", "dj"]
    must_change_password: bool


class DjAccountResponse(BaseModel):
    id: str
    username: str
    full_name: str
    email: str
    is_banned: bool
    created_at: str


class DjBanRequest(BaseModel):
    is_banned: bool


class AuthStatusResponse(BaseModel):
    has_admin: bool
    user: UserResponse | None
    bootstrap_available: bool
    bootstrap_token_required: bool


class BootstrapRequest(BaseModel):
    username: str = Field(min_length=3, max_length=30)
    full_name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=6, max_length=128)
    setup_token: str | None = Field(default=None, max_length=256)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=30)
    password: str = Field(min_length=1, max_length=128)


class DjApplicationCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    experience: str = Field(min_length=10, max_length=1000)


class DjApplicationResponse(BaseModel):
    id: str
    full_name: str
    email: str
    experience: str
    submitted_at: str


class AdApplicationCreate(BaseModel):
    contact_name: str = Field(min_length=2, max_length=100)
    business_name: str = Field(default="", max_length=100)
    email: str = Field(min_length=5, max_length=254)
    phone: str = Field(default="", max_length=30)
    ad_details: str = Field(min_length=10, max_length=1000)


class AdApplicationResponse(BaseModel):
    id: str
    contact_name: str
    business_name: str
    email: str
    phone: str
    ad_details: str
    submitted_at: str


class LiveAdImageResponse(BaseModel):
    id: str
    url: str


class LiveAdResponse(BaseModel):
    text: str
    images: list[LiveAdImageResponse]
    updated_at: str | None


class ApproveApplicationRequest(BaseModel):
    username: str = Field(min_length=3, max_length=30)


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(min_length=12, max_length=128)


class ApprovalResponse(BaseModel):
    user: UserResponse
    temporary_password: str


class BroadcastStateRequest(BaseModel):
    controller_id: str = Field(min_length=1, max_length=128)
    track_id: str | None
    is_playing: bool
    position_seconds: float = Field(ge=0)


class BroadcastClaimRequest(BaseModel):
    controller_id: str = Field(min_length=1, max_length=128)
    track_id: str
    position_seconds: float = Field(ge=0)


class NextTrackRequest(BaseModel):
    next_track_id: str | None


class PlaylistTrackRequest(BaseModel):
    track_id: str = Field(min_length=1, max_length=128)


class BroadcastStateResponse(BaseModel):
    track: TrackResponse | None
    next_track: TrackResponse | None
    controller_id: str | None
    is_playing: bool
    position_seconds: float
    revision: int
    updated_at: str


def current_user(request: Request) -> dict[str, object]:
    token = request.cookies.get(SESSION_COOKIE)
    user = authentication.user_for_session(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in as a DJ to continue.")
    if bool(user["must_change_password"]):
        raise HTTPException(status_code=403, detail="Change your temporary password first.")
    return user


def current_dj(
    user: Annotated[dict[str, object], Depends(current_user)],
) -> dict[str, object]:
    if user["role"] not in {"admin", "dj"}:
        raise HTTPException(status_code=403, detail="DJ access is required.")
    return user


def current_admin(
    user: Annotated[dict[str, object], Depends(current_user)],
) -> dict[str, object]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user


def optional_user(request: Request) -> dict[str, object] | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return authentication.user_for_session(token)


def set_session_cookie(
    response: Response, request: Request, token: str
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=authentication.SESSION_SECONDS,
        httponly=True,
        secure=APP_ENV == "production" or request.url.scheme == "https",
        samesite="strict",
        path="/",
    )


def enforce_public_rate_limit(
    request: Request,
    *,
    scope: str,
    max_requests: int,
    window_seconds: int,
) -> None:
    if request.client is None or not request.client.host:
        raise HTTPException(
            status_code=503,
            detail="The server could not determine the request source.",
        )
    retry_after = rate_limiting.check_rate_limit(
        scope=scope,
        client_address=request.client.host,
        max_requests=max_requests,
        window_seconds=window_seconds,
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait before trying again.",
            headers={"Retry-After": str(retry_after)},
        )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    if APP_ENV == "production" and not (UI_DIST_DIR / "index.html").is_file():
        raise RuntimeError(
            "The production UI is missing. Build it with 'npm run build' in ui/."
        )
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    ADS_DIR.mkdir(parents=True, exist_ok=True)
    initialize_database()
    music_library.backfill_track_hashes()
    music_library.backfill_track_durations()
    yield


app = FastAPI(
    title="KASTIGO Local API",
    description="Local music library, streaming, and playback activity API.",
    lifespan=lifespan,
    docs_url=None if APP_ENV == "production" else "/docs",
    redoc_url=None if APP_ENV == "production" else "/redoc",
    openapi_url=None if APP_ENV == "production" else "/openapi.json",
)


def serialize_track(track: dict[str, object]) -> TrackResponse:
    return TrackResponse(
        id=str(track["id"]),
        title=str(track["title"]),
        artist=str(track["artist"]),
        file_name=str(track["file_name"]),
        content_type=str(track["content_type"]),
        category=str(track["category"]),
        duration_seconds=(
            float(cast(float, track["duration_seconds"]))
            if track.get("duration_seconds") is not None
            else None
        ),
        size_bytes=int(cast(int, track["size_bytes"])),
        created_at=str(track["created_at"]),
        stream_url=f"/api/tracks/{track['id']}/stream",
    )


@app.get("/api/health")
def health() -> dict[str, int | str]:
    return {
        "status": "ready",
        "database": "SQLite",
        "track_count": music_library.track_count(),
    }


@app.get("/api/auth/status", response_model=AuthStatusResponse)
def auth_status(request: Request) -> dict[str, object]:
    user = optional_user(request)
    has_admin = authentication.has_admin()
    return {
        "has_admin": has_admin,
        "user": authentication.public_user(user) if user is not None else None,
        "bootstrap_available": not has_admin
        and (APP_ENV != "production" or bool(BOOTSTRAP_TOKEN)),
        "bootstrap_token_required": APP_ENV == "production" or bool(BOOTSTRAP_TOKEN),
    }


@app.post("/api/auth/bootstrap", response_model=UserResponse, status_code=201)
def bootstrap_admin(
    payload: BootstrapRequest, request: Request, response: Response
) -> dict[str, object]:
    enforce_public_rate_limit(
        request, scope="admin-bootstrap", max_requests=10, window_seconds=900
    )
    if APP_ENV == "production" and not BOOTSTRAP_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="First-admin setup is disabled until the server setup token is configured.",
        )
    if BOOTSTRAP_TOKEN and not hmac.compare_digest(
        (payload.setup_token or "").encode("utf-8"),
        BOOTSTRAP_TOKEN.encode("utf-8"),
    ):
        raise HTTPException(status_code=403, detail="The server setup token is invalid.")
    try:
        user = authentication.create_first_admin(
            username=payload.username,
            full_name=payload.full_name,
            password=payload.password,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="That username is already in use.") from error

    token, _ = authentication.create_session(str(user["id"]))
    set_session_cookie(response, request, token)
    return authentication.public_user(user)


@app.post("/api/auth/login", response_model=UserResponse)
def login(
    payload: LoginRequest, request: Request, response: Response
) -> dict[str, object]:
    enforce_public_rate_limit(
        request, scope="login", max_requests=20, window_seconds=900
    )
    if authentication.login_is_locked(payload.username):
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Try again in 15 minutes.",
        )
    user = authentication.authenticate(payload.username, payload.password)
    if user is None:
        authentication.record_login_failure(payload.username)
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    authentication.clear_login_failures(payload.username)
    token, _ = authentication.create_session(str(user["id"]))
    set_session_cookie(response, request, token)
    return authentication.public_user(user)


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        authentication.revoke_session(token)
    response.delete_cookie(
        key=SESSION_COOKIE,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    response.status_code = 204
    return response


def user_for_password_change(request: Request) -> dict[str, object]:
    token = request.cookies.get(SESSION_COOKIE)
    user = authentication.user_for_session(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in as a DJ to continue.")
    return user


@app.post("/api/auth/password", response_model=UserResponse)
def change_password(
    payload: ChangePasswordRequest,
    user: Annotated[dict[str, object], Depends(user_for_password_change)],
) -> dict[str, object]:
    changed = authentication.change_password(
        user_id=str(user["id"]),
        password=payload.new_password,
    )
    return authentication.public_user(changed)


@app.post(
    "/api/auth/applications",
    response_model=DjApplicationResponse,
    status_code=201,
)
def submit_dj_application(
    payload: DjApplicationCreate, request: Request
) -> dict[str, object]:
    enforce_public_rate_limit(
        request, scope="dj-application", max_requests=5, window_seconds=3600
    )
    try:
        return authentication.create_dj_application(
            full_name=payload.full_name,
            email=payload.email,
            experience=payload.experience,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail="A pending application already exists for that email address.",
        ) from error


@app.post(
    "/api/public/ad-applications",
    response_model=AdApplicationResponse,
    status_code=201,
)
def submit_ad_application(
    payload: AdApplicationCreate, request: Request
) -> dict[str, object]:
    enforce_public_rate_limit(
        request, scope="ad-application", max_requests=5, window_seconds=3600
    )
    try:
        return advertising.create_ad_application(
            contact_name=payload.contact_name,
            business_name=payload.business_name,
            email=payload.email,
            phone=payload.phone,
            ad_details=payload.ad_details,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get(
    "/api/admin/applications",
    response_model=list[DjApplicationResponse],
)
def get_dj_applications(
    _: Annotated[dict[str, object], Depends(current_admin)],
) -> list[dict[str, object]]:
    return authentication.list_pending_applications()


@app.get("/api/admin/djs", response_model=list[DjAccountResponse])
def get_dj_accounts(
    _: Annotated[dict[str, object], Depends(current_admin)],
) -> list[dict[str, object]]:
    return authentication.list_dj_accounts()


@app.put(
    "/api/admin/djs/{dj_id}/ban",
    response_model=DjAccountResponse,
)
def set_dj_banned(
    dj_id: str,
    payload: DjBanRequest,
    _: Annotated[dict[str, object], Depends(current_admin)],
) -> dict[str, object]:
    try:
        return authentication.set_dj_banned(
            user_id=dj_id,
            is_banned=payload.is_banned,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.delete("/api/admin/djs/{dj_id}", status_code=204)
def delete_dj_account(
    dj_id: str,
    _: Annotated[dict[str, object], Depends(current_admin)],
) -> Response:
    try:
        authentication.delete_dj_account(user_id=dj_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=204)


@app.post(
    "/api/admin/applications/{application_id}/approve",
    response_model=ApprovalResponse,
)
def approve_dj_application(
    application_id: str,
    payload: ApproveApplicationRequest,
    admin: Annotated[dict[str, object], Depends(current_admin)],
) -> dict[str, object]:
    try:
        user, temporary_password = authentication.approve_application(
            application_id=application_id,
            username=payload.username,
            admin_id=str(admin["id"]),
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="That username is already in use.") from error
    return {
        "user": authentication.public_user(user),
        "temporary_password": temporary_password,
    }


@app.post("/api/admin/applications/{application_id}/reject", status_code=204)
def reject_dj_application(
    application_id: str,
    admin: Annotated[dict[str, object], Depends(current_admin)],
) -> Response:
    try:
        authentication.reject_application(
            application_id=application_id,
            admin_id=str(admin["id"]),
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=204)


@app.get(
    "/api/admin/ad-applications",
    response_model=list[AdApplicationResponse],
)
def get_ad_applications(
    _: Annotated[dict[str, object], Depends(current_admin)],
) -> list[dict[str, object]]:
    return advertising.list_pending_ad_applications()


@app.get("/api/public/live-ad", response_model=LiveAdResponse)
def get_public_live_ad(response: Response) -> dict[str, object | None]:
    response.headers["Cache-Control"] = "no-store"
    return advertising.get_live_ad()


@app.get("/api/public/live-ad/image")
@app.get("/api/public/live-ad/images/{image_id}")
def get_public_live_ad_image(image_id: str | None = None) -> FileResponse:
    try:
        image = advertising.live_ad_image(image_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if image is None:
        raise HTTPException(status_code=404, detail="No live advertisement image is published.")
    image_path, content_type = image
    return FileResponse(
        image_path,
        media_type=content_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.put("/api/admin/live-ad", response_model=LiveAdResponse)
async def update_live_ad(
    _: Annotated[dict[str, object], Depends(current_admin)],
    text: Annotated[str, Form(max_length=1000)] = "",
    images: Annotated[list[UploadFile] | None, File()] = None,
    remove_images: Annotated[bool, Form()] = False,
    append_images: Annotated[bool, Form()] = False,
) -> dict[str, object]:
    image_uploads: list[bytes] = []
    try:
        selected_images = [image for image in images or [] if image.filename]
        if len(selected_images) > MAX_AD_IMAGE_COUNT:
            raise HTTPException(
                status_code=422,
                detail=f"Upload no more than {MAX_AD_IMAGE_COUNT} advertisement images.",
            )
        for image in selected_images:
            image_data = await image.read(MAX_AD_IMAGE_BYTES + 1)
            if len(image_data) > MAX_AD_IMAGE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Advertisement images cannot exceed 5 MB.",
                )
            image_uploads.append(image_data)
        return advertising.update_live_ad(
            text=text,
            image_uploads=image_uploads or None,
            remove_images=remove_images,
            append_images=append_images,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        for image in images or []:
            await image.close()


@app.delete("/api/admin/live-ad", status_code=204)
def delete_live_ad(
    _: Annotated[dict[str, object], Depends(current_admin)],
) -> Response:
    advertising.clear_live_ad()
    return Response(status_code=204)


@app.post("/api/admin/ad-applications/{application_id}/review", status_code=204)
def review_ad_application(
    application_id: str,
    _: Annotated[dict[str, object], Depends(current_admin)],
) -> Response:
    try:
        advertising.mark_ad_application_reviewed(application_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=204)


@app.get("/api/public/broadcast", response_model=BroadcastStateResponse)
def get_public_broadcast() -> dict[str, object]:
    state = broadcast.current_state()
    track = state["track"]
    next_track = state["next_track"]
    return {
        **state,
        "track": serialize_track(track) if isinstance(track, dict) else None,
        "next_track": (
            serialize_track(next_track) if isinstance(next_track, dict) else None
        ),
    }


@app.put("/api/broadcast/next-track", status_code=204)
def update_next_track(
    payload: NextTrackRequest,
    _: Annotated[dict[str, object], Depends(current_dj)],
) -> Response:
    try:
        broadcast.set_next_track(payload.next_track_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=204)


@app.put("/api/broadcast/state", response_model=BroadcastStateResponse)
def update_broadcast_state(
    payload: BroadcastStateRequest,
    _: Annotated[dict[str, object], Depends(current_admin)],
) -> dict[str, object]:
    try:
        state = broadcast.set_current_state(
            controller_id=payload.controller_id,
            track_id=payload.track_id,
            is_playing=payload.is_playing,
            position_seconds=payload.position_seconds,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    track = state["track"]
    next_track = state["next_track"]
    return {
        **state,
        "track": serialize_track(track) if isinstance(track, dict) else None,
        "next_track": (
            serialize_track(next_track) if isinstance(next_track, dict) else None
        ),
    }


@app.post("/api/broadcast/claim", response_model=BroadcastStateResponse)
def claim_broadcast_control(
    payload: BroadcastClaimRequest,
    _: Annotated[dict[str, object], Depends(current_admin)],
) -> dict[str, object]:
    try:
        state = broadcast.claim_control(
            controller_id=payload.controller_id,
            track_id=payload.track_id,
            position_seconds=payload.position_seconds,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    track = state["track"]
    next_track = state["next_track"]
    return {
        **state,
        "track": serialize_track(track) if isinstance(track, dict) else None,
        "next_track": (
            serialize_track(next_track) if isinstance(next_track, dict) else None
        ),
    }


@app.get("/api/tracks", response_model=list[TrackResponse])
def get_tracks(
    _: Annotated[dict[str, object], Depends(current_dj)],
) -> list[TrackResponse]:
    return [serialize_track(track) for track in music_library.list_tracks()]


@app.get("/api/playlist", response_model=list[TrackResponse])
def get_playlist(
    _: Annotated[dict[str, object], Depends(current_dj)],
) -> list[TrackResponse]:
    return [serialize_track(track) for track in playlist.list_playlist()]


@app.post("/api/playlist", response_model=list[TrackResponse])
def add_playlist_track(
    payload: PlaylistTrackRequest,
    _: Annotated[dict[str, object], Depends(current_dj)],
) -> list[TrackResponse]:
    try:
        tracks = playlist.add_track(payload.track_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return [serialize_track(track) for track in tracks]


@app.put("/api/playlist/next", response_model=list[TrackResponse])
def move_playlist_track_next(
    payload: PlaylistTrackRequest,
    _: Annotated[dict[str, object], Depends(current_dj)],
) -> list[TrackResponse]:
    try:
        tracks = playlist.play_track_next(payload.track_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return [serialize_track(track) for track in tracks]


@app.delete("/api/playlist/{track_id}", response_model=list[TrackResponse])
def remove_playlist_track(
    track_id: str,
    _: Annotated[dict[str, object], Depends(current_dj)],
) -> list[TrackResponse]:
    return [serialize_track(track) for track in playlist.remove_track(track_id)]


@app.post("/api/tracks", response_model=TrackResponse, status_code=201)
async def upload_track(
    _: Annotated[dict[str, object], Depends(current_dj)],
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    artist: Annotated[str, Form()] = "Unknown Artist",
    category: Annotated[str, Form()] = "music",
) -> TrackResponse:
    original_name = Path((file.filename or "").replace("\\", "/")).name
    extension = Path(original_name).suffix.lower()
    if not original_name or extension not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Choose an audio file ({', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}).",
        )

    clean_title = (title or "").strip() or Path(original_name).stem
    clean_artist = artist.strip() or "Unknown Artist"
    if len(clean_title) > 200 or len(clean_artist) > 120:
        raise HTTPException(
            status_code=422,
            detail="Track title must be at most 200 characters and artist at most 120.",
        )

    file_path = MUSIC_DIR / f"{uuid4().hex}{extension}"
    saved = False
    size_bytes = 0
    try:
        with file_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Audio uploads cannot exceed 250 MB.",
                    )
                destination.write(chunk)
        if size_bytes == 0:
            raise HTTPException(status_code=422, detail="The selected audio file is empty.")

        try:
            duration_seconds = music_library.audio_duration_seconds(file_path)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        try:
            track = music_library.register_track(
                title=clean_title,
                artist=clean_artist,
                file_name=original_name,
                file_path=file_path,
                content_type=mimetypes.guess_type(original_name)[0]
                or "application/octet-stream",
                size_bytes=size_bytes,
                category=category,
                duration_seconds=duration_seconds,
            )
        except music_library.DuplicateTrackError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        saved = True
        return serialize_track(track)
    finally:
        await file.close()
        if not saved and file_path.exists():
            file_path.unlink()


@app.delete("/api/tracks/{track_id}", status_code=204)
def remove_track(
    track_id: str,
    _: Annotated[dict[str, object], Depends(current_admin)],
) -> None:
    track = music_library.delete_track(track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found.")

    file_path = Path(str(track["file_path"]))
    try:
        file_path.unlink(missing_ok=True)
    except OSError as error:
        LOGGER.exception(
            "Track %s was removed from the library, but its file could not be deleted.",
            track_id,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "The track was removed from the library, but its audio file could not "
                "be deleted. Contact the station administrator."
            ),
        ) from error


@app.get("/api/tracks/{track_id}/stream")
def stream_track(track_id: str, request: Request) -> FileResponse:
    track = music_library.get_track(track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found.")
    user = optional_user(request)
    if (
        user is None or bool(user["must_change_password"])
    ) and not broadcast.is_current_track(track_id):
        raise HTTPException(status_code=403, detail="This track is not currently on air.")
    try:
        file_path = music_library.track_file_path(track)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(file_path, media_type=str(track["content_type"]))


@app.get("/api/monitoring/events", response_model=list[MonitorEventResponse])
def get_monitoring_events(
    _: Annotated[dict[str, object], Depends(current_dj)],
) -> list[dict[str, object]]:
    return monitoring.list_events()


@app.post(
    "/api/monitoring/events",
    response_model=MonitorEventResponse,
    status_code=201,
)
def create_monitoring_event(
    event: MonitorEventCreate,
    _: Annotated[dict[str, object], Depends(current_dj)],
) -> dict[str, object]:
    if event.track_id is not None and music_library.get_track(event.track_id) is None:
        raise HTTPException(status_code=404, detail="Track not found.")
    return monitoring.record_event(
        event_type=event.event_type,
        message=event.message,
        track_id=event.track_id,
    )


if UI_DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(UI_DIST_DIR), html=True), name="web")

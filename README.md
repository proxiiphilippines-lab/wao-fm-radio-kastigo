# KASTIGO LIVE BROADCASTER

A local web-based control room for **WAO FM RADIO KASTIGO 88.3 FM**. The Vite
frontend talks to a FastAPI backend running on this PC. Music files, library
records, and browser playback activity are stored locally.

## Requirements

- Windows 10 or later
- Python 3.10 or later
- Node.js 18 or later
- OBS Studio for a separate streaming workflow

## Start the application

Open two PowerShell terminals in the project folder.

In the first terminal, install Python dependencies and start the API:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

In the second terminal, install frontend dependencies and start Vite:

```powershell
cd ui
npm install
npm run dev
```

Open the local address printed by Vite (normally `http://127.0.0.1:5173`).
The API is available at `http://127.0.0.1:8000`; its interactive API
documentation is at `http://127.0.0.1:8000/docs`.

### Offline operation

After Python and frontend dependencies have been installed, KASTIGO's admin
player works without Internet access. On the admin PC, keep both local servers
running and open `http://127.0.0.1:5173`; the API, music files in `data/music/`,
and SQLite database in `data/kastigo.sqlite3` are all on that PC. Other PCs do
not need Internet either, but they must still be connected to the same working
local network to reach the admin PC. FM transmission is handled separately by
the station's existing radio automation and audio chain.

### Open the listener page from another PC on your Wi-Fi

- On the broadcaster PC, run `ipconfig` and note its IPv4 address.
- On the other PC, open `http://<broadcaster-ip>:5173` (replace the placeholder with that address).
- Vite serves the web page on the LAN and proxies `/api` requests to the API on this PC. The API itself stays bound to `127.0.0.1`; do not open port 8000 to the network.
- If Windows Firewall blocks access, allow Node.js/Vite on a **Private** network for TCP port `5173`, limited to the local subnet. Do not allow this on a Public network or use an untrusted Wi-Fi network. The development server uses HTTP, not HTTPS.

## Music and local data

- From the Music Library page, choose a folder to upload its MP3, WAV, FLAC, M4A, OGG, and AAC files together. The selected folder name becomes the category for its audio files, including files in its subfolders.
- The category picker includes the built-in **Music**, **Advertisement**, and **Drama** categories plus folder names used for uploads. Audio files with identical contents are rejected as duplicates, even if their names differ.
- Audio uploads are limited to 250 MB per file.
- Playback continues while switching between Overview, Music Library, and Activity in the same browser.
- Playback automatically crossfades into the next queued track over three seconds; the outgoing track fades down as the incoming track fades up. Listener pages follow the same live transition and show “No next track yet” when the queue is empty.
- The playlist is stored in SQLite and shared by signed-in admins and DJs. They can add tracks, play a track now or next, and remove items; the queue shows each track's duration and updates the listener's next-track state.
- Only the station admin can start, pause, or change live playback. DJ control rooms and listener pages follow the admin's on-air track and playback state. Because browsers block automatic audio until a user gesture, press **Enable live audio** or **Listen** once on each device; that device then follows the shared player. Mute and volume remain local to each device.
- The full track library and playback history are available to every signed-in DJ. DJs can add tracks to the shared playlist and choose the next queued track; only the station admin can start, pause, or change the on-air track.
- The Overview console uses Deck A for the next playlist, Deck B for the live player, and Deck C to preview the current promotion photo, playing track, and live promotion text. The queue, music library, and playback history remain below the decks.
- The listener page shows the current track and the first queued next track; only the current track has Listen and Mute controls.
- Logging out opens a TV-style listener page with station branding, the current track, DJ login/application forms, and any active station advertisement.
- The listener page has an **Apply for ads** form. Requests are saved in SQLite and station admins can review them under **Ad requests**.
- Admins can open **Ad operations** in the Workspace to publish scrolling listener-screen text and up to 50 JPG/JPEG, PNG, WebP, GIF, BMP, TIFF, HEIC/HEIF, or AVIF banners (5 MB each). Uploaded banners are converted to browser-friendly images. Use **Add more photos** to append images to the current slideshow; banners rotate every five seconds and cover the listener ad space. The separate **Apply for ads** button remains available to listeners.
- Listener audio starts after the listener presses **Listen** once to enable audio on that device. It then follows the admin's on-air playback and cannot pause the station. The **Mute** button silences audio on that listener device only.
- Music files and SQLite stay on the broadcaster PC. Listener devices on the same LAN can view the page and play the current on-air track through the Vite proxy; this is not an Internet broadcast.
- On the control desk, the track list and activity history scroll independently from the player controls.
- Audio files are saved in `data/music/`.
- Published ad images are saved in `data/ads/`.
- Library records and audio durations, the shared playlist, playback activity, DJ accounts, applications, ad requests, live-ad details, sessions, playback ownership, and current broadcast state are stored in `data/kastigo.sqlite3`.
- The API binds to `127.0.0.1`; only the Vite web server is exposed to the LAN.
- `data/` is excluded from version control.

The listener stream is limited to devices that can reach the broadcaster PC on
the same LAN. The app does **not** capture Windows audio
input, inspect OtsAV, or report OBS connection/broadcast status; those
integrations need to be implemented separately.

## Production web deployment

The two-server Vite workflow above is for development and trusted-LAN testing,
not public hosting. For a web deployment, build the frontend and let FastAPI
serve the resulting files:

```powershell
cd ui
npm ci
npm run build
cd ..
$env:KASTIGO_ENV = "production"
$env:KASTIGO_HOST = "127.0.0.1"
$env:KASTIGO_PORT = "8000"
$env:KASTIGO_BOOTSTRAP_TOKEN = (py -c "import secrets; print(secrets.token_urlsafe(32))")
$env:KASTIGO_BOOTSTRAP_TOKEN
python main.py
```

Open the printed setup token in the terminal and enter it on the first-admin
setup form. Production bootstrap tokens must be at least 32 characters.
Production startup fails if the frontend build is missing. The
server disables interactive API documentation in production and marks session
cookies Secure. After creating the administrator, clear the token and restart
the server:

```powershell
Remove-Item Env:KASTIGO_BOOTSTRAP_TOKEN
```

Keep the API bound to `127.0.0.1` and put an HTTPS reverse proxy (for example,
Caddy or Nginx) in front of it. Publish only the proxy's HTTPS port, configure
its certificate and hostname. The API also limits login attempts to 20 per
client per 15 minutes, first-admin setup to 10 per 15 minutes, and each public
application form to 5 submissions per client per hour. Configure additional
proxy-level limits as a second layer. Do not expose port `8000` directly to the
Internet. `KASTIGO_HOST` and `KASTIGO_PORT` can be set for a different local
binding; changing them does not configure TLS.

The app is still a local-file music player, not an Internet radio encoder or
FM/OBS integration. Make sure a reverse proxy and hosting plan can support the
expected number of concurrent audio listeners before relying on it publicly.

### Data backups

Stop the API before making a backup so the SQLite database and media files are
copied as one consistent set. Copy the complete `data/` directory to a
separate, access-restricted location; it contains the library database,
accounts, application records, audio, and ad images. Protect backups because
the database contains password hashes and private application information.
To restore, stop the API, preserve the current `data/` directory, then restore
the complete backed-up directory before restarting the app.

## DJ accounts

- On first launch, choose **Set up the first administrator** on the listener page. SQLite enforces a single admin account; production setup also requires the server token described above.
- DJs sign in to the existing Overview, music library, and player. The admin has a separate dashboard for application review and a link to the live operations desk.
- DJs can submit an application from **Sign up as DJ**. The station admin reviews applications from the control room.
- When approving an application, the admin assigns a username and receives a temporary password to give to the DJ. The DJ must set a new password at first sign-in.
- Admins can use **DJ management** in the sidebar to see total, active, and banned DJ accounts, restore or ban access, or permanently delete an account. Banning revokes existing DJ sessions.
- A bootstrap password shorter than 12 characters is temporary and requires a 12-character password change before the admin can enter the dashboard.
- **Log Out** returns to the listener preview. The current broadcast state is local and does not provide remote streaming or live video.

## Project layout

- `main.py`: starts the local API server
- `api/`: FastAPI endpoints for accounts, applications, music, streaming, and playback activity
- `services/`: authentication, broadcast state, music library, and monitoring operations
- `config/`: local paths and SQLite connection/schema
- `ui/`: Vite, React, and TypeScript frontend
- `tests/`: SQLite persistence, authentication, and HTTP integration tests

## Verify

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests
cd ui
npm run build
```

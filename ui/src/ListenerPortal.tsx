import { useEffect, useState, type FormEvent } from "react";

import { apiUrl, type LiveAd, type Track } from "./api";

export type PortalMode = "viewer" | "login" | "signup" | "bootstrap" | "ads";

interface ListenerPortalProps {
  mode: PortalMode;
  hasAdmin: boolean;
  bootstrapAvailable: boolean;
  bootstrapTokenRequired: boolean;
  track: Track | null;
  nextTrack: Track | null;
  liveAd: LiveAd | null;
  broadcastPlaying: boolean;
  audioEnabled: boolean;
  playerMuted: boolean;
  busy: boolean;
  error: string;
  notice: string;
  onModeChange: (mode: PortalMode) => void;
  onEnableAudio: () => void;
  onToggleMute: () => void;
  onLogin: (data: { username: string; password: string }) => void;
  onSignup: (data: { full_name: string; email: string; experience: string }) => void;
  onBootstrap: (data: {
    username: string;
    full_name: string;
    password: string;
    setup_token: string;
  }) => void;
  onAdApplication: (data: {
    contact_name: string;
    business_name: string;
    email: string;
    phone: string;
    ad_details: string;
  }) => void;
}

export function ListenerPortal({
  mode,
  hasAdmin,
  bootstrapAvailable,
  bootstrapTokenRequired,
  track,
  nextTrack,
  liveAd,
  broadcastPlaying,
  audioEnabled,
  playerMuted,
  busy,
  error,
  notice,
  onModeChange,
  onEnableAudio,
  onToggleMute,
  onLogin,
  onSignup,
  onBootstrap,
  onAdApplication,
}: ListenerPortalProps) {
  const adImages = liveAd?.images ?? [];
  const adImageKey = adImages.map((image) => image.id).join("|");
  const [adImageIndex, setAdImageIndex] = useState(0);

  useEffect(() => {
    setAdImageIndex(0);
  }, [adImageKey]);

  useEffect(() => {
    if (adImages.length < 2) return;
    const timer = window.setInterval(() => {
      setAdImageIndex((index) => (index + 1) % adImages.length);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [adImageKey]);

  const currentAdImage = adImages.length
    ? adImages[adImageIndex % adImages.length]
    : null;

  const submitLogin = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    onLogin({
      username: String(form.get("username") ?? ""),
      password: String(form.get("password") ?? ""),
    });
  };

  const submitSignup = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    onSignup({
      full_name: String(form.get("full_name") ?? ""),
      email: String(form.get("email") ?? ""),
      experience: String(form.get("experience") ?? ""),
    });
  };

  const submitBootstrap = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    onBootstrap({
      username: String(form.get("username") ?? ""),
      full_name: String(form.get("full_name") ?? ""),
      password: String(form.get("password") ?? ""),
      setup_token: String(form.get("setup_token") ?? ""),
    });
  };

  const submitAdApplication = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    onAdApplication({
      contact_name: String(form.get("contact_name") ?? ""),
      business_name: String(form.get("business_name") ?? ""),
      email: String(form.get("email") ?? ""),
      phone: String(form.get("phone") ?? ""),
      ad_details: String(form.get("ad_details") ?? ""),
    });
  };

  return (
    <div className="viewer-page">
      <header className="viewer-header">
        <div className="viewer-brand">
          <span className="brand-mark">K</span>
          <span>
            <strong>KASTIGO TV</strong>
            <small>WAO FM RADIO · 88.3 FM</small>
          </span>
        </div>
        <span className="viewer-local-tag"><i /> LOCAL LISTENER PREVIEW</span>
      </header>

      <main className="viewer-layout">
        <div className="viewer-primary">
          <section className="viewer-screen" aria-label="Live video placeholder">
            <div className="viewer-screen-top">
              <span>WAO FM · 88.3</span>
              <span className="viewer-screen-badge">
                <i /> {broadcastPlaying ? "AUDIO ON AIR" : "STANDBY"}
              </span>
            </div>
            <div className="viewer-screen-center">
              <span className="viewer-screen-logo">K</span>
              <p>LIVE VIDEO FEED</p>
              <strong>WAO FM RADIO KASTIGO</strong>
              <small>Video source will appear here when connected.</small>
            </div>
            {liveAd?.text && (
              <div className="viewer-ad-ticker" role="note" aria-label="Advertisement">
                <div
                  className="viewer-ad-ticker-track"
                  style={{ animationDuration: `${Math.max(32, liveAd.text.length * 0.25)}s` }}
                >
                  <span className="viewer-ad-ticker-copy">
                    {liveAd.text}<span className="viewer-ad-ticker-separator" aria-hidden="true">-</span>
                  </span>
                  <span className="viewer-ad-ticker-copy" aria-hidden="true">
                    {liveAd.text}<span className="viewer-ad-ticker-separator">-</span>
                  </span>
                </div>
              </div>
            )}
            <span className="viewer-screen-footer">TV VIEWER · LOCAL PREVIEW</span>
          </section>

          <section className="viewer-now-playing">
            <div className="viewer-now-art">♫</div>
            <div className="viewer-now-copy">
              <small>{track ? "NOW PLAYING" : "STATION MUSIC"}</small>
              <strong>{track?.title ?? "Waiting for the next track"}</strong>
              <span>{track?.artist ?? "WAO FM RADIO KASTIGO · 88.3 FM"}</span>
              <div className="viewer-next-track">
                <small>NEXT TRACK</small>
                <strong>{nextTrack?.title ?? "No next track queued"}</strong>
                {nextTrack && <span>{nextTrack.artist}</span>}
              </div>
            </div>
            <button
              className="viewer-listen-button"
              onClick={onEnableAudio}
              disabled={!track || audioEnabled}
              aria-label={audioEnabled ? "Listener audio enabled" : "Enable listener audio"}
            >
              {audioEnabled ? "✓" : "▶"}
              <span>{audioEnabled ? "AUDIO ENABLED" : "LISTEN"}</span>
            </button>
            <button
              className="viewer-mute-button"
              onClick={onToggleMute}
              disabled={!track}
              aria-pressed={playerMuted}
              aria-label={playerMuted ? "Unmute listener audio" : "Mute listener audio"}
            >
              {playerMuted ? "UNMUTE" : "MUTE"}
            </button>
          </section>
          <p className="viewer-disclaimer">
            Press Listen once to enable audio on this device. After that, playback follows the station admin. Use Mute to silence this device.
          </p>
        </div>

        <aside className="viewer-sidebar">
          <section className="viewer-side-card viewer-program-card">
            <p className="viewer-eyebrow">ON THE AIR</p>
            <strong>WAO FM RADIO KASTIGO</strong>
            <span>88.3 FM <i>·</i> LIVE MUSIC</span>
            <div className={`viewer-audio-status${broadcastPlaying ? " is-live" : ""}`}>
              <i /> {broadcastPlaying ? "DJ PLAYER IS ACTIVE" : "WAITING FOR A DJ"}
            </div>
          </section>

          <section
            className={`viewer-ad-card${currentAdImage ? " has-ad-images" : ""}`}
            aria-label="Advertisement"
          >
            <span>ADVERTISEMENT</span>
            {currentAdImage ? (
              <img
                key={currentAdImage.id}
                src={apiUrl(currentAdImage.url)}
                alt={`WAO FM advertisement ${adImageIndex + 1} of ${adImages.length}`}
              />
            ) : (
              <>
                <strong>AD SPACE</strong>
                <small>Promote your business on WAO FM.</small>
              </>
            )}
            <button
              className="button button-primary viewer-ad-apply"
              onClick={() => onModeChange("ads")}
            >
              Apply for ads
            </button>
          </section>

          <section className="viewer-dj-card">
            <p className="viewer-eyebrow">DJ ACCESS</p>
            <p className="viewer-dj-note">You don't need an account to listen — just press Listen above. DJ access is for station staff only.</p>
            <button className="button button-quiet" onClick={() => onModeChange("login")}>
              Log in as DJ
            </button>
            <button className="button button-quiet" onClick={() => onModeChange("signup")}>
              Sign up as DJ
            </button>
            {!hasAdmin && bootstrapAvailable && (
              <button className="viewer-setup-link" onClick={() => onModeChange("bootstrap")}>
                Set up the first administrator
              </button>
            )}
            {!hasAdmin && !bootstrapAvailable && (
              <span className="viewer-dj-note">
                First-admin setup is disabled until the server operator configures it.
              </span>
            )}
          </section>
        </aside>
      </main>

      {(error || notice) && (
        <div className={`viewer-message${error ? " is-error" : ""}`} role={error ? "alert" : "status"}>
          {error || notice}
        </div>
      )}

      {mode !== "viewer" && (
        <div className="portal-modal-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) onModeChange("viewer");
        }}>
          <section className="portal-modal" role="dialog" aria-modal="true" aria-labelledby="portal-title">
            <button
              className="portal-close"
              onClick={() => onModeChange("viewer")}
              aria-label="Close"
            >
              ×
            </button>
            {error && <p className="portal-form-error" role="alert">{error}</p>}
            {mode === "login" && (
              <>
                <p className="viewer-eyebrow">BROADCASTER ACCESS</p>
                <h2 id="portal-title">Log in as DJ</h2>
                <p className="portal-description">Use the username and password provided by the station admin.</p>
                <form className="portal-form" onSubmit={submitLogin}>
                  <label>
                    <span>USERNAME</span>
                    <input name="username" autoComplete="username" minLength={3} maxLength={30} required />
                  </label>
                  <label>
                    <span>PASSWORD</span>
                    <input name="password" type="password" autoComplete="current-password" maxLength={128} required />
                  </label>
                  <button className="button button-primary" disabled={busy}>
                    {busy ? "Signing in..." : "Log in"}
                  </button>
                </form>
                <button className="portal-switch" onClick={() => onModeChange("signup")}>
                  Need DJ access? <b>Apply here</b>
                </button>
              </>
            )}
            {mode === "signup" && (
              <>
                <p className="viewer-eyebrow">DJ APPLICATION</p>
                <h2 id="portal-title">Apply to become a DJ</h2>
                <p className="portal-description">
                  An admin reviews your information. If approved, the admin will give you a username and temporary password.
                </p>
                <form className="portal-form" onSubmit={submitSignup}>
                  <label>
                    <span>FULL NAME</span>
                    <input name="full_name" autoComplete="name" minLength={2} maxLength={100} required />
                  </label>
                  <label>
                    <span>EMAIL</span>
                    <input name="email" type="email" autoComplete="email" maxLength={254} required />
                  </label>
                  <label>
                    <span>DJ EXPERIENCE / APPLICATION</span>
                    <textarea name="experience" minLength={10} maxLength={1000} rows={4} required />
                  </label>
                  <button className="button button-primary" disabled={busy}>
                    {busy ? "Sending..." : "Submit application"}
                  </button>
                </form>
              </>
            )}
            {mode === "bootstrap" && (
              <>
                <p className="viewer-eyebrow">FIRST-TIME SETUP</p>
                <h2 id="portal-title">Create station admin</h2>
                <p className="portal-description">
                  Create the single station administrator. Passwords under 12 characters are temporary and must be changed before access.
                </p>
                {bootstrapAvailable ? (
                  <form className="portal-form" onSubmit={submitBootstrap}>
                    {bootstrapTokenRequired && (
                      <label>
                        <span>SERVER SETUP TOKEN</span>
                        <input name="setup_token" type="password" autoComplete="off" maxLength={256} required />
                      </label>
                    )}
                    <label>
                      <span>ADMIN NAME</span>
                      <input name="full_name" autoComplete="name" minLength={2} maxLength={100} required />
                    </label>
                    <label>
                      <span>USERNAME</span>
                      <input name="username" autoComplete="username" defaultValue="admin123admin" minLength={3} maxLength={30} required />
                    </label>
                    <label>
                      <span>TEMPORARY PASSWORD <small>6+ characters</small></span>
                      <input name="password" type="password" autoComplete="new-password" minLength={6} maxLength={128} required />
                    </label>
                    <button className="button button-primary" disabled={busy}>
                      {busy ? "Creating account..." : "Create administrator"}
                    </button>
                  </form>
                ) : (
                  <p className="portal-description">
                    First-admin setup is disabled. Ask the server operator to configure a setup token.
                  </p>
                )}
              </>
            )}
            {mode === "ads" && (
              <>
                <p className="viewer-eyebrow">ADVERTISING ENQUIRY</p>
                <h2 id="portal-title">Apply for ad space</h2>
                <p className="portal-description">
                  Share your contact details and what you want to promote. The station admin will review your request.
                </p>
                <form className="portal-form" onSubmit={submitAdApplication}>
                  <label>
                    <span>YOUR NAME</span>
                    <input name="contact_name" autoComplete="name" minLength={2} maxLength={100} required />
                  </label>
                  <label>
                    <span>BUSINESS / ORGANIZATION <small>OPTIONAL</small></span>
                    <input name="business_name" autoComplete="organization" maxLength={100} />
                  </label>
                  <label>
                    <span>EMAIL</span>
                    <input name="email" type="email" autoComplete="email" maxLength={254} required />
                  </label>
                  <label>
                    <span>PHONE <small>OPTIONAL</small></span>
                    <input name="phone" type="tel" autoComplete="tel" maxLength={30} />
                  </label>
                  <label>
                    <span>WHAT WOULD YOU LIKE TO ADVERTISE?</span>
                    <textarea name="ad_details" minLength={10} maxLength={1000} rows={4} required />
                  </label>
                  <button className="button button-primary" disabled={busy}>
                    {busy ? "Sending request..." : "Send ad request"}
                  </button>
                </form>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

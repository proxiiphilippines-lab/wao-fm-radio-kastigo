import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  api,
  apiUrl,
  ApiError,
  type AdApplication,
  type ApprovedDj,
  type AuthUser,
  type BroadcastState,
  type DjAccount,
  type DjApplication,
  type Health,
  type LiveAd,
  type MonitorEvent,
  type Track,
  type TrackCategory,
} from "./api";
import { ListenerPortal, type PortalMode } from "./ListenerPortal";

type View =
  | "admin-dashboard"
  | "dashboard"
  | "library"
  | "activity"
  | "applications"
  | "dj-management"
  | "ad-applications"
  | "live-ads";

const MAX_AD_IMAGES = 50;
const CROSSFADE_SECONDS = 3;
const TRACK_CATEGORY_OPTIONS: { value: TrackCategory; label: string }[] = [
  { value: "music", label: "Music" },
  { value: "advertisement", label: "Advertisement" },
  { value: "drama", label: "Drama" },
];

interface AudioCrossfade {
  fromIndex: number;
  toIndex: number;
  from: HTMLAudioElement;
  to: HTMLAudioElement;
  fromTrack: Track | null;
  track: Track;
  startedAt: number;
  durationMs: number;
  intervalId: number;
}

const navigation: { id: View; label: string; icon: string }[] = [
  { id: "dashboard", label: "Overview", icon: "O" },
  { id: "admin-dashboard", label: "Admin dashboard", icon: "A" },
  { id: "library", label: "Music library", icon: "M" },
  { id: "activity", label: "Activity log", icon: "A" },
  { id: "applications", label: "DJ applications", icon: "D" },
  { id: "dj-management", label: "DJ management", icon: "M" },
  { id: "ad-applications", label: "Ad requests", icon: "$" },
  { id: "live-ads", label: "Ad operations", icon: "P" },
];

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds: number): string {
  const totalSeconds = Math.floor(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const remainder = String(totalSeconds % 60).padStart(2, "0");
  if (minutes >= 60) {
    return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}:${remainder}`;
  }
  return `${minutes}:${remainder}`;
}

function userInitials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length > 1) {
    return `${parts[0].charAt(0)}${parts[parts.length - 1].charAt(0)}`.toUpperCase();
  }
  return (parts[0]?.slice(0, 2) || "DJ").toUpperCase();
}

function synchronizedPosition(state: BroadcastState | null): number {
  return state?.position_seconds ?? 0;
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatTrackCategory(category: TrackCategory): string {
  return TRACK_CATEGORY_OPTIONS.find((item) => item.value === category)?.label
    ?? category.replace(/[_-]+/g, " ").replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

function suggestUsername(fullName: string): string {
  const username = fullName
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, ".")
    .replace(/^[._-]+|[._-]+$/g, "")
    .slice(0, 30);
  return username.length >= 3 ? username : "new.dj";
}

function App() {
  const [view, setView] = useState<View>("dashboard");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [hasAdmin, setHasAdmin] = useState(false);
  const [bootstrapAvailable, setBootstrapAvailable] = useState(true);
  const [bootstrapTokenRequired, setBootstrapTokenRequired] = useState(false);
  const [authReady, setAuthReady] = useState(false);
  const [portalMode, setPortalMode] = useState<PortalMode>("viewer");
  const [tracks, setTracks] = useState<Track[]>([]);
  const [events, setEvents] = useState<MonitorEvent[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [broadcastState, setBroadcastState] = useState<BroadcastState | null>(null);
  const [applications, setApplications] = useState<DjApplication[]>([]);
  const [djAccounts, setDjAccounts] = useState<DjAccount[]>([]);
  const [djAccountsLoading, setDjAccountsLoading] = useState(false);
  const [adApplications, setAdApplications] = useState<AdApplication[]>([]);
  const [liveAd, setLiveAd] = useState<LiveAd | null>(null);
  const [promoImageIndex, setPromoImageIndex] = useState(0);
  const [approvedDj, setApprovedDj] = useState<ApprovedDj | null>(null);
  const [currentTrack, setCurrentTrack] = useState<Track | null>(null);
  const [queue, setQueue] = useState<Track[]>([]);
  const [playing, setPlaying] = useState(false);
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [selectedTrackCategory, setSelectedTrackCategory] = useState<TrackCategory | null>(null);
  const [categoryPickerOpen, setCategoryPickerOpen] = useState(false);
  const [adText, setAdText] = useState("");
  const [removeAdImages, setRemoveAdImages] = useState(false);
  const [selectedAdImages, setSelectedAdImages] = useState<File[]>([]);
  const [listenerMuted, setListenerMuted] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadMode, setUploadMode] = useState<"file" | "folder">("folder");
  const [singleUploadCategory, setSingleUploadCategory] = useState<TrackCategory>("music");
  const fileInput = useRef<HTMLInputElement>(null);
  const adImageInput = useRef<HTMLInputElement>(null);
  const audioElements = [
    useRef<HTMLAudioElement>(null),
    useRef<HTMLAudioElement>(null),
  ] as const;
  const [activeAudioIndex, setActiveAudioIndex] = useState(0);
  const activeAudioIndexRef = useRef(0);
  const audioTrackIds = useRef<(string | null)[]>([null, null]);
  const playbackRequested = useRef(false);
  const playbackClaimedRef = useRef(false);
  const controllerIdRef = useRef(
    `control-${Date.now()}-${Math.random().toString(36).slice(2)}`,
  );
  const claimSequenceRef = useRef(0);
  const broadcastRevisionRef = useRef(-1);
  const applyBroadcastState = useCallback((state: BroadcastState) => {
    if (state.revision <= broadcastRevisionRef.current) return false;
    broadcastRevisionRef.current = state.revision;
    setBroadcastState(state);
    return true;
  }, []);
  const volumeRef = useRef(1);
  const mutedRef = useRef(false);
  const suppressedPauseEvents = useRef(new Set<number>());
  const crossfade = useRef<AudioCrossfade | null>(null);
  const liveAdImageKey = liveAd?.images.map((image) => image.id).join("|") ?? "";
  const liveAdImageCount = liveAd?.images.length ?? 0;
  const currentPromoImage = liveAdImageCount
    ? liveAd?.images[promoImageIndex % liveAdImageCount] ?? null
    : null;

  useLayoutEffect(() => {
    if (uploadOpen && uploadMode === "folder") {
      fileInput.current?.setAttribute("webkitdirectory", "");
    } else {
      fileInput.current?.removeAttribute("webkitdirectory");
    }
  }, [uploadMode, uploadOpen]);

  function relinquishLocalPlayback() {
    playbackClaimedRef.current = false;
    playbackRequested.current = false;
    const transition = crossfade.current;
    if (transition) {
      window.clearInterval(transition.intervalId);
      transition.to.pause();
      transition.from.volume = volumeRef.current;
      transition.to.volume = volumeRef.current;
      crossfade.current = null;
    }
    audioElements.forEach((element, index) => {
      const player = element.current;
      if (!player || player.paused) return;
      suppressedPauseEvents.current.add(index);
      player.pause();
      window.setTimeout(() => suppressedPauseEvents.current.delete(index), 250);
    });
    setPlaying(false);
  }

  const refresh = useCallback(async () => {
    try {
      const [nextTracks, nextEvents, nextHealth, nextPlaylist] = await Promise.all([
        api.tracks(),
        api.events(),
        api.health(),
        api.playlist(),
      ]);
      setTracks(nextTracks);
      setEvents(nextEvents);
      setHealth(nextHealth);
      setQueue(nextPlaylist);
      setError("");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) {
        setUser(null);
        setPortalMode("viewer");
        return;
      }
      setError(
        reason instanceof Error ? reason.message : "The local API is unavailable.",
      );
      setHealth(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!user || user.must_change_password) return;
    let active = true;
    const synchronizePlaylist = async () => {
      try {
        const sharedPlaylist = await api.playlist();
        if (active) setQueue(sharedPlaylist);
      } catch (reason) {
        if (!active) return;
        if (reason instanceof ApiError && reason.status === 401) {
          setUser(null);
          setPortalMode("viewer");
          return;
        }
        setError(
          reason instanceof Error ? reason.message : "Could not load the shared playlist.",
        );
      }
    };
    void synchronizePlaylist();
    const timer = window.setInterval(() => void synchronizePlaylist(), 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [user]);

  useEffect(() => {
    let active = true;
    void api.authStatus().then((status) => {
      if (!active) return;
      setHasAdmin(status.has_admin);
      setBootstrapAvailable(status.bootstrap_available);
      setBootstrapTokenRequired(status.bootstrap_token_required);
      setUser(status.user);
      if (status.user) {
        setView(status.user.role === "admin" ? "admin-dashboard" : "dashboard");
      }
      if (status.user?.must_change_password) setPortalMode("login");
    }).catch((reason: unknown) => {
      if (active) {
        setError(reason instanceof Error ? reason.message : "Could not check DJ sign-in.");
      }
    }).finally(() => {
      if (active) setAuthReady(true);
    });
    return () => {
      active = false;
    };
  }, []);

  const refreshPublicBroadcast = useCallback(async () => {
    try {
      const state = await api.publicBroadcast();
      if (applyBroadcastState(state)) setCurrentTrack(state.track);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not load the listener broadcast.",
      );
    }
  }, [applyBroadcastState]);

  const refreshPublicLiveAd = useCallback(async () => {
    try {
      setLiveAd(await api.publicLiveAd());
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not load live advertisements.",
      );
    }
  }, []);

  useEffect(() => {
    if (!authReady) return;
    if (user && !user.must_change_password) {
      void refresh();
      const timer = window.setInterval(() => void refresh(), 15000);
      return () => window.clearInterval(timer);
    }
    void refreshPublicBroadcast();
    const broadcastTimer = window.setInterval(() => void refreshPublicBroadcast(), 1000);
    return () => {
      window.clearInterval(broadcastTimer);
    };
  }, [authReady, refresh, refreshPublicBroadcast, user]);

  useEffect(() => {
    if (!authReady) return;
    void refreshPublicLiveAd();
    const timer = window.setInterval(() => void refreshPublicLiveAd(), 5000);
    return () => window.clearInterval(timer);
  }, [authReady, refreshPublicLiveAd]);

  useEffect(() => {
    setPromoImageIndex(0);
  }, [liveAdImageKey]);

  useEffect(() => {
    if (liveAdImageCount < 2) return;
    const timer = window.setInterval(() => {
      setPromoImageIndex((index) => (index + 1) % liveAdImageCount);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [liveAdImageCount, liveAdImageKey]);

  useEffect(() => {
    if (!user || user.must_change_password || user.role !== "admin" || view !== "applications") return;
    let active = true;
    void api.djApplications().then((items) => {
      if (active) setApplications(items);
    }).catch((reason: unknown) => {
      if (active) {
        setError(reason instanceof Error ? reason.message : "Could not load DJ applications.");
      }
    });
    return () => {
      active = false;
    };
  }, [user, view]);

  useEffect(() => {
    if (!user || user.must_change_password || user.role !== "admin" || view !== "dj-management") return;
    let active = true;
    setDjAccountsLoading(true);
    void api.djAccounts().then((items) => {
      if (active) setDjAccounts(items);
    }).catch((reason: unknown) => {
      if (active) {
        setError(reason instanceof Error ? reason.message : "Could not load DJ accounts.");
      }
    }).finally(() => {
      if (active) setDjAccountsLoading(false);
    });
    return () => {
      active = false;
    };
  }, [user, view]);

  useEffect(() => {
    if (!user || user.must_change_password || user.role !== "admin" || view !== "admin-dashboard") return;
    let active = true;
    void Promise.all([
      api.djApplications(),
      api.djAccounts(),
      api.adApplications(),
      api.publicBroadcast(),
      api.publicLiveAd(),
    ]).then(([djItems, djAccounts, adItems, state, ad]) => {
      if (!active) return;
      setApplications(djItems);
      setDjAccounts(djAccounts);
      setAdApplications(adItems);
      if (applyBroadcastState(state)) setCurrentTrack(state.track);
      setLiveAd(ad);
    }).catch((reason: unknown) => {
      if (active) {
        setError(reason instanceof Error ? reason.message : "Could not load admin dashboard.");
      }
    });
    return () => {
      active = false;
    };
  }, [applyBroadcastState, user, view]);

  useEffect(() => {
    if (!user || user.must_change_password || user.role !== "admin" || view !== "live-ads") return;
    let active = true;
    void api.publicLiveAd().then((ad) => {
      if (!active) return;
      setLiveAd(ad);
      setAdText(ad.text);
      setRemoveAdImages(false);
      setSelectedAdImages([]);
    }).catch((reason: unknown) => {
      if (active) {
        setError(reason instanceof Error ? reason.message : "Could not load live advertisements.");
      }
    });
    return () => {
      active = false;
    };
  }, [user, view]);

  useEffect(() => {
    if (!user || user.must_change_password || user.role !== "admin" || view !== "ad-applications") return;
    let active = true;
    void api.adApplications().then((items) => {
      if (active) setAdApplications(items);
    }).catch((reason: unknown) => {
      if (active) {
        setError(reason instanceof Error ? reason.message : "Could not load advertising requests.");
      }
    });
    return () => {
      active = false;
    };
  }, [user, view]);

  const recordPlaybackEvent = async (
    eventType: "playback_started" | "playback_paused" | "playback_ended" | "playback_error",
    message: string,
    trackId = currentTrack?.id,
  ) => {
    if (user?.role !== "admin" || !trackId) return;
    try {
      await api.recordEvent({
        event_type: eventType,
        message,
        track_id: trackId,
      });
      void refresh();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not save playback activity.",
      );
    }
  };

  const publishBroadcastState = useCallback(async (state: {
    track_id: string | null;
    is_playing: boolean;
    position_seconds: number;
  }) => {
    if (user?.role !== "admin" || user.must_change_password) return;
    try {
      applyBroadcastState(await api.setBroadcast({
        ...state,
        controller_id: controllerIdRef.current,
      }));
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        relinquishLocalPlayback();
        setNotice("Playback is now controlled by another operator.");
      }
      setError(
        reason instanceof Error ? reason.message : "Could not update the listener feed.",
      );
    }
  }, [applyBroadcastState, user]);

  const handleLogin = async (credentials: { username: string; password: string }) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const signedIn = await api.login(credentials.username, credentials.password);
      setListenerMuted(false);
      mutedRef.current = false;
      audioElements.forEach((element) => {
        if (element.current) element.current.muted = false;
      });
      setUser(signedIn);
      setHasAdmin(true);
      setPortalMode("viewer");
      setView(signedIn.role === "admin" ? "admin-dashboard" : "dashboard");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "DJ sign-in failed.");
    } finally {
      setBusy(false);
    }
  };

  const handleBootstrap = async (details: {
    username: string;
    full_name: string;
    password: string;
    setup_token: string;
  }) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const admin = await api.bootstrapAdmin(details);
      setListenerMuted(false);
      mutedRef.current = false;
      audioElements.forEach((element) => {
        if (element.current) element.current.muted = false;
      });
      setUser(admin);
      setHasAdmin(true);
      setPortalMode("viewer");
      setView("admin-dashboard");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create the administrator.");
    } finally {
      setBusy(false);
    }
  };

  const handleApplication = async (details: {
    full_name: string;
    email: string;
    experience: string;
  }) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.applyForDj(details);
      setPortalMode("viewer");
      setNotice("Application sent. An admin will review it and provide credentials if approved.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not submit the DJ application.");
    } finally {
      setBusy(false);
    }
  };

  const handleAdApplication = async (details: {
    contact_name: string;
    business_name: string;
    email: string;
    phone: string;
    ad_details: string;
  }) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.applyForAds(details);
      setPortalMode("viewer");
      setNotice("Ad request sent. The station admin will review it.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not submit the ad request.");
    } finally {
      setBusy(false);
    }
  };

  const handlePublishLiveAd = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updatedAd = await api.publishLiveAd({
        text: String(form.get("text") ?? ""),
        images: selectedAdImages,
        remove_images: form.get("remove_images") === "on",
        append_images: selectedAdImages.length > 0 && Boolean(liveAd?.images.length),
      });
      setLiveAd(updatedAd);
      setAdText(updatedAd.text);
      setRemoveAdImages(false);
      setSelectedAdImages([]);
      if (adImageInput.current) adImageInput.current.value = "";
      setNotice("Live advertisement published to the listener page.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not publish the live advertisement.");
    } finally {
      setBusy(false);
    }
  };

  const handleClearLiveAd = async () => {
    if (!window.confirm("Stop the current live advertisement and remove its image?")) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.clearLiveAd();
      setLiveAd({ text: "", images: [], updated_at: null });
      setAdText("");
      setRemoveAdImages(false);
      setSelectedAdImages([]);
      if (adImageInput.current) adImageInput.current.value = "";
      setNotice("Live advertisement stopped.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not stop the live advertisement.");
    } finally {
      setBusy(false);
    }
  };

  const handlePasswordChange = async (newPassword: string) => {
    setBusy(true);
    setError("");
    try {
      const updatedUser = await api.changePassword(newPassword);
      setUser(updatedUser);
      setView(updatedUser.role === "admin" ? "admin-dashboard" : "dashboard");
      setNotice("Password updated. Welcome to the control room.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update the password.");
    } finally {
      setBusy(false);
    }
  };

  const handleLogout = async () => {
    setBusy(true);
    setError("");
    try {
      await api.logout();
      setUser(null);
      setView("dashboard");
      setQueue([]);
      setApprovedDj(null);
      setPortalMode("viewer");
      setNotice("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not log out.");
    } finally {
      setBusy(false);
    }
  };

  const handleApproveApplication = async (applicationId: string, username: string) => {
    setError("");
    try {
      const approved = await api.approveDjApplication(applicationId, username);
      setApprovedDj(approved);
      setApplications((current) => current.filter((application) => application.id !== applicationId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not approve the DJ application.");
    }
  };

  const handleRejectApplication = async (applicationId: string) => {
    setError("");
    try {
      await api.rejectDjApplication(applicationId);
      setApplications((current) => current.filter((application) => application.id !== applicationId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not reject the DJ application.");
    }
  };

  const handleToggleDjBan = async (account: DjAccount) => {
    const shouldBan = !account.is_banned;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await api.setDjBanned(account.id, shouldBan);
      setDjAccounts((current) =>
        current.map((item) => item.id === updated.id ? updated : item),
      );
      setNotice(
        shouldBan
          ? `${account.full_name}'s DJ account has been banned.`
          : `${account.full_name}'s DJ account has been restored.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update the DJ account.");
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteDj = async (account: DjAccount) => {
    if (!window.confirm(
      `Permanently delete ${account.full_name}'s DJ account? This cannot be undone.`,
    )) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.deleteDjAccount(account.id);
      setDjAccounts((current) => current.filter((item) => item.id !== account.id));
      setNotice(`${account.full_name}'s DJ account was deleted.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete the DJ account.");
    } finally {
      setBusy(false);
    }
  };

  const handleReviewAdApplication = async (applicationId: string) => {
    setError("");
    try {
      await api.reviewAdApplication(applicationId);
      setAdApplications((current) =>
        current.filter((application) => application.id !== applicationId),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not mark the ad request reviewed.");
    }
  };

  const activeAudioPlayer = () =>
    audioElements[activeAudioIndexRef.current].current;

  const removeFromQueue = (track: Track) => {
    void api.removePlaylistTrack(track.id).then(setQueue).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "Could not remove track from playlist.");
    });
  };

  const cancelCrossfade = () => {
    const transition = crossfade.current;
    if (!transition) return;
    window.clearInterval(transition.intervalId);
    transition.to.pause();
    transition.from.volume = volumeRef.current;
    transition.to.volume = volumeRef.current;
    crossfade.current = null;
  };

  const claimAndStartPlayback = (track: Track, positionSeconds = 0) => {
    if (user?.role !== "admin") return;
    const sequence = ++claimSequenceRef.current;
    relinquishLocalPlayback();
    setCurrentTrack(track);

    void api.claimBroadcast({
      controller_id: controllerIdRef.current,
      track_id: track.id,
      position_seconds: positionSeconds,
    }).then((state) => {
      if (sequence !== claimSequenceRef.current) return;
      applyBroadcastState(state);
      if (state.controller_id !== controllerIdRef.current) {
        relinquishLocalPlayback();
        setCurrentTrack(state.track);
        setNotice("Another operator took control before playback could start.");
        return;
      }

      playbackClaimedRef.current = true;
      playbackRequested.current = true;
      setCurrentTrack(state.track ?? track);
      const index = activeAudioIndexRef.current;
      const player = audioElements[index].current;
      if (!player) {
        relinquishLocalPlayback();
        setError("The live player is unavailable.");
        return;
      }
      if (audioTrackIds.current[index] !== track.id) {
        player.src = apiUrl(track.stream_url);
        player.load();
        audioTrackIds.current[index] = track.id;
      }
      player.volume = volumeRef.current;
      player.muted = mutedRef.current;

      const startPlayback = () => {
        if (sequence !== claimSequenceRef.current || !playbackClaimedRef.current) return;
        if (positionSeconds > 0 && Number.isFinite(player.duration)) {
          player.currentTime = Math.min(
            positionSeconds,
            Math.max(0, player.duration - 0.1),
          );
        }
        void player.play().catch(() => {
          if (sequence !== claimSequenceRef.current) return;
          playbackClaimedRef.current = false;
          playbackRequested.current = false;
          setPlaying(false);
          setError("Playback could not start. Check the audio file and try again.");
          void publishBroadcastState({
            track_id: track.id,
            is_playing: false,
            position_seconds: player.currentTime,
          });
        });
      };
      if (player.readyState >= HTMLMediaElement.HAVE_METADATA) {
        startPlayback();
      } else {
        player.addEventListener("loadedmetadata", startPlayback, { once: true });
      }
    }).catch((reason: unknown) => {
      if (sequence !== claimSequenceRef.current) return;
      relinquishLocalPlayback();
      setError(reason instanceof Error ? reason.message : "Could not take playback control.");
    });
  };

  const finishCrossfade = () => {
    const transition = crossfade.current;
    if (!transition) return;
    window.clearInterval(transition.intervalId);
    if (user?.role === "admin" && transition.fromTrack) {
      void recordPlaybackEvent(
        "playback_ended",
        `Finished playing ${transition.fromTrack.title}`,
        transition.fromTrack.id,
      );
    }
    activeAudioIndexRef.current = transition.toIndex;
    transition.from.pause();
    transition.from.volume = volumeRef.current;
    transition.to.volume = volumeRef.current;
    audioTrackIds.current[transition.toIndex] = transition.track.id;
    crossfade.current = null;
    setActiveAudioIndex(transition.toIndex);
    setPlaying(true);

    if (user?.role === "admin" && !user.must_change_password) {
      removeFromQueue(transition.track);
      setCurrentTrack(transition.track);
      void publishBroadcastState({
        track_id: transition.track.id,
        is_playing: true,
        position_seconds: transition.to.currentTime,
      });
    } else {
      setCurrentTrack(transition.track);
    }
  };

  const beginCrossfade = (
    fromIndex: number,
    track: Track,
    durationMs: number,
    startPosition = 0,
  ) => {
    if (crossfade.current || fromIndex !== activeAudioIndexRef.current) return;
    const from = audioElements[fromIndex].current;
    const toIndex = 1 - fromIndex;
    const to = audioElements[toIndex].current;
    if (!from || !to) return;

    to.pause();
    to.src = apiUrl(track.stream_url);
    to.volume = 0;
    to.muted = mutedRef.current;
    audioTrackIds.current[toIndex] = track.id;

    const transition: AudioCrossfade = {
      fromIndex,
      toIndex,
      from,
      to,
      fromTrack: currentTrack,
      track,
      startedAt: performance.now(),
      durationMs: Math.max(100, durationMs),
      intervalId: 0,
    };
    crossfade.current = transition;

    const startIncomingTrack = () => {
      if (crossfade.current !== transition) return;
      if (startPosition > 0 && Number.isFinite(to.duration)) {
        to.currentTime = Math.min(startPosition, Math.max(0, to.duration - 0.1));
      }
      void to.play().then(() => {
        if (crossfade.current !== transition) return;
        transition.startedAt = performance.now();
        if (Number.isFinite(from.duration)) {
          const remainingMs = Math.max(
            100,
            (from.duration - from.currentTime) * 1000,
          );
          transition.durationMs = Math.min(transition.durationMs, remainingMs);
        }
        if (user?.role === "admin" && !user.must_change_password) {
          removeFromQueue(track);
          setCurrentTrack(track);
          void publishBroadcastState({
            track_id: track.id,
            is_playing: true,
            position_seconds: to.currentTime,
          });
        }
        transition.intervalId = window.setInterval(() => {
          const progress = Math.min(
            1,
            (performance.now() - transition.startedAt) / transition.durationMs,
          );
          from.volume = volumeRef.current * Math.cos(progress * Math.PI / 2);
          to.volume = volumeRef.current * Math.sin(progress * Math.PI / 2);
          if (progress >= 1) finishCrossfade();
        }, 40);
      }).catch(() => {
        if (crossfade.current === transition) {
          crossfade.current = null;
          to.volume = volumeRef.current;
          audioTrackIds.current[toIndex] = null;
          setError("The next track could not start for the crossfade.");
        }
      });
    };
    to.load();
    if (to.readyState >= HTMLMediaElement.HAVE_METADATA) {
      startIncomingTrack();
    } else {
      to.addEventListener("loadedmetadata", startIncomingTrack, { once: true });
    }
  };

  const playTrack = (track: Track) => {
    if (user?.role !== "admin") return;
    cancelCrossfade();
    removeFromQueue(track);
    claimAndStartPlayback(track);
  };

  const enableLocalAudio = () => {
    if (!currentTrack || user?.role === "admin") return;
    const player = activeAudioPlayer();
    if (!player) return;

    playbackRequested.current = true;
    setAudioEnabled(true);
    if (audioTrackIds.current[activeAudioIndexRef.current] !== currentTrack.id) {
      player.src = apiUrl(currentTrack.stream_url);
      player.load();
      audioTrackIds.current[activeAudioIndexRef.current] = currentTrack.id;
    }

    const seekToBroadcastPosition = () => {
      if (audioTrackIds.current[activeAudioIndexRef.current] !== currentTrack.id) return;
      const position = Math.max(0, broadcastState?.position_seconds ?? 0);
      if (Number.isFinite(player.duration)) {
        player.currentTime = Math.min(position, Math.max(0, player.duration - 0.1));
      }
    };
    player.volume = volumeRef.current;
    player.muted = mutedRef.current || !broadcastState?.is_playing;
    if (player.readyState >= HTMLMediaElement.HAVE_METADATA) {
      seekToBroadcastPosition();
    } else {
      player.addEventListener("loadedmetadata", seekToBroadcastPosition, { once: true });
    }

    void player.play().then(() => {
      if (!broadcastState?.is_playing) {
        player.pause();
        seekToBroadcastPosition();
        player.muted = mutedRef.current;
        setPlaying(false);
      }
    }).catch(() => {
      playbackRequested.current = false;
      setAudioEnabled(false);
      player.muted = mutedRef.current;
      setError("Audio could not start on this device. Press Listen again to enable it.");
    });
  };

  const toggleListenerMute = () => {
    const player = activeAudioPlayer();
    if (!player) return;
    player.muted = !player.muted;
    mutedRef.current = player.muted;
    audioElements.forEach((element) => {
      if (element.current) element.current.muted = player.muted;
    });
    setListenerMuted(player.muted);
  };

  useEffect(() => {
    const index = activeAudioIndexRef.current;
    const player = audioElements[index].current;
    if (!player) return;
    if (!currentTrack && crossfade.current) cancelCrossfade();
    if (!currentTrack) {
      if (!player.paused) {
        suppressedPauseEvents.current.add(index);
        player.pause();
        window.setTimeout(() => suppressedPauseEvents.current.delete(index), 250);
      }
      audioTrackIds.current[index] = null;
      setPlaying(false);
      return;
    }
    if (crossfade.current?.track.id === currentTrack.id) return;
    const isAdmin = user?.role === "admin";
    const trackChanged = audioTrackIds.current[index] !== currentTrack.id;
    if (
      trackChanged &&
      !isAdmin &&
      audioEnabled &&
      !player.paused &&
      audioTrackIds.current[index] &&
      broadcastState?.is_playing
    ) {
      const ageSeconds = Math.max(
        0,
        (Date.now() - Date.parse(broadcastState.updated_at)) / 1000,
      );
      const targetPosition = Math.max(
        0,
        broadcastState.position_seconds + ageSeconds,
      );
      beginCrossfade(
        index,
        currentTrack,
        Math.max(100, (CROSSFADE_SECONDS - targetPosition) * 1000),
        targetPosition,
      );
      return;
    }
    if (trackChanged) {
      if (crossfade.current) cancelCrossfade();
      if (!player.paused) {
        suppressedPauseEvents.current.add(index);
        player.pause();
        window.setTimeout(() => suppressedPauseEvents.current.delete(index), 250);
      }
      player.src = apiUrl(currentTrack.stream_url);
      player.load();
      player.volume = volumeRef.current;
      player.muted = mutedRef.current;
      audioTrackIds.current[index] = currentTrack.id;

      let active = true;
      const startFollower = () => {
        if (!active || isAdmin || !audioEnabled || !broadcastState?.is_playing) return;
        const ageSeconds = Math.max(
          0,
          (Date.now() - Date.parse(broadcastState.updated_at)) / 1000,
        );
        const targetPosition = Math.max(0, broadcastState.position_seconds + ageSeconds);
        if (Number.isFinite(player.duration)) {
          player.currentTime = Math.min(targetPosition, Math.max(0, player.duration - 0.1));
        }
        void player.play().catch(() => {
          setPlaying(false);
          if (!isAdmin) {
            playbackRequested.current = false;
            setAudioEnabled(false);
          }
          setError("Audio could not start on this device. Press Listen to enable it.");
        });
      };
      if (player.readyState >= HTMLMediaElement.HAVE_METADATA) {
        startFollower();
      } else {
        player.addEventListener("loadedmetadata", startFollower, { once: true });
      }
      return () => {
        active = false;
        player.removeEventListener("loadedmetadata", startFollower);
      };
    }

    if (isAdmin || !audioEnabled || !broadcastState) return;
    if (!broadcastState.is_playing) {
      if (!player.paused) {
        suppressedPauseEvents.current.add(index);
        player.pause();
        window.setTimeout(() => suppressedPauseEvents.current.delete(index), 250);
      }
      setPlaying(false);
      return;
    }

    const ageSeconds = Math.max(
      0,
      (Date.now() - Date.parse(broadcastState.updated_at)) / 1000,
    );
    const targetPosition = Math.max(0, broadcastState.position_seconds + ageSeconds);
    if (Number.isFinite(player.duration)) {
      const boundedPosition = Math.min(targetPosition, Math.max(0, player.duration - 0.1));
      if (player.paused || Math.abs(player.currentTime - boundedPosition) > 2.5) {
        player.currentTime = boundedPosition;
      }
    }
    if (player.paused) {
      void player.play().catch(() => {
        setPlaying(false);
        playbackRequested.current = false;
        setAudioEnabled(false);
        setError("Audio could not start on this device. Press Listen to enable it.");
      });
    }
  }, [
    activeAudioIndex,
    audioEnabled,
    broadcastState?.is_playing,
    broadcastState?.position_seconds,
    broadcastState?.updated_at,
    currentTrack,
    user,
  ]);

  useEffect(() => {
    if (!user || user.must_change_password) return;
    let active = true;
    const synchronizeBroadcast = async () => {
      try {
        const state = await api.publicBroadcast();
        if (!active) return;
        if (!applyBroadcastState(state)) return;
        if (
          user?.role === "admin" &&
          state.controller_id !== controllerIdRef.current
        ) {
          if (
            playbackClaimedRef.current ||
            playbackRequested.current ||
            audioElements.some((element) => element.current && !element.current.paused)
          ) {
            claimSequenceRef.current += 1;
            relinquishLocalPlayback();
            setNotice("Playback is now controlled by another operator.");
          }
          setCurrentTrack((current) =>
            current?.id === state.track?.id ? current : state.track,
          );
          return;
        }
        setCurrentTrack((current) =>
          current?.id === state.track?.id ? current : state.track,
        );
      } catch (reason) {
        if (!active) return;
        setError(
          reason instanceof Error ? reason.message : "Could not synchronize the live player.",
        );
      }
    };
    void synchronizeBroadcast();
    const timer = window.setInterval(() => void synchronizeBroadcast(), 500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [user]);

  useEffect(() => {
    if (
      !user ||
      user.must_change_password ||
      !playbackClaimedRef.current ||
      !playing ||
      !currentTrack
    ) return;
    const timer = window.setInterval(() => {
      const transition = crossfade.current;
      const player =
        transition && transition.track.id === currentTrack.id
          ? transition.to
          : activeAudioPlayer();
      if (player) {
        void publishBroadcastState({
          track_id: currentTrack.id,
          is_playing: true,
          position_seconds: player.currentTime,
        });
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [currentTrack, playing, publishBroadcastState, user]);

  const handleUpload = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const files = Array.from(fileInput.current?.files ?? []);
    if (files.length === 0) {
      setError(uploadMode === "folder"
        ? "Choose a music folder to add to your library."
        : "Choose one audio file to add to your library.");
      return;
    }
    let categoryName = singleUploadCategory;
    if (uploadMode === "folder") {
      const folderNames = new Set(files.map((file) =>
        file.webkitRelativePath.replace(/\\/g, "/").split("/")[0].trim(),
      ));
      const folderName = files[0]?.webkitRelativePath.replace(/\\/g, "/").split("/")[0];
      if (folderNames.size !== 1 || !folderName?.trim()) {
        setError("Select one folder at a time so its name can be used as the category.");
        return;
      }
      categoryName = folderName.trim();
    } else if (files.length !== 1) {
      setError("Select exactly one audio file in Single file mode.");
      return;
    }
    if (categoryName.length > 80) {
      setError("The category name must be 80 characters or fewer.");
      return;
    }
    const audioFiles = files.filter((file) => /\.(mp3|wav|flac|m4a|ogg|aac)$/i.test(file.name));
    const unsupportedCount = files.length - audioFiles.length;
    if (audioFiles.length === 0) {
      setError(uploadMode === "folder"
        ? "The selected folder contains no supported audio files."
        : "Choose a supported audio file: MP3, WAV, FLAC, M4A, OGG, or AAC.");
      return;
    }

    setBusy(true);
    setError("");
    let uploadedCount = 0;
    let duplicateCount = 0;
    const failures: string[] = [];
    try {
      for (const file of audioFiles) {
        try {
          await api.upload(file, "", "Unknown Artist", categoryName);
          uploadedCount += 1;
        } catch (reason) {
          if (reason instanceof ApiError && reason.status === 409) {
            duplicateCount += 1;
          } else {
            const detail = reason instanceof Error ? reason.message : "Upload failed.";
            failures.push(`${file.name}: ${detail}`);
          }
        }
      }
      if (uploadedCount > 0) await refresh();
      const summary = [`${uploadedCount} of ${audioFiles.length} audio files added to "${categoryName}".`];
      if (duplicateCount > 0) summary.push(`${duplicateCount} duplicate file(s) skipped.`);
      if (unsupportedCount > 0) summary.push(`${unsupportedCount} unsupported file(s) skipped.`);
      if (failures.length > 0) {
        const detail = failures.slice(0, 3).join(" ");
        const moreFailures = failures.length > 3 ? ` ${failures.length - 3} more upload(s) failed.` : "";
        setError(`${summary.join(" ")} Upload issues: ${detail}${moreFailures}`);
      } else {
        setNotice(summary.join(" "));
      }
      setUploadOpen(false);
      form.reset();
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (track: Track) => {
    if (!window.confirm(`Remove "${track.title}" and its local audio file?`)) return;
    try {
      await api.removeTrack(track.id);
      setQueue(await api.playlist());
      if (currentTrack?.id === track.id) {
        playbackRequested.current = false;
        audioElements.forEach((element) => element.current?.pause());
        setCurrentTrack(null);
        setPlaying(false);
      }
      setNotice(`${track.title} was removed.`);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not remove track.");
    }
  };

  const addToQueue = (track: Track) => {
    void api.addPlaylistTrack(track.id).then(setQueue).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "Could not add track to playlist.");
    });
  };

  const playTrackNext = (track: Track) => {
    if (user?.role === "admin" && (!currentTrack || activeAudioPlayer()?.ended)) {
      playTrack(track);
      return;
    }
    void api.playPlaylistTrackNext(track.id).then(setQueue).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "Could not move track to the start of the playlist.");
    });
  };

  const handleAudioPlay = (index: number) => {
    if (index !== activeAudioIndexRef.current) return;
    if (user?.role !== "admin") {
      playbackRequested.current = true;
      setAudioEnabled(true);
      setPlaying(true);
      return;
    }
    if (!playbackClaimedRef.current) {
      const player = audioElements[index].current;
      if (currentTrack) {
        claimAndStartPlayback(currentTrack, player?.currentTime ?? 0);
      } else {
        relinquishLocalPlayback();
      }
      return;
    }
    playbackRequested.current = true;
    setPlaying(true);
    if (!currentTrack) return;
    void recordPlaybackEvent(
      "playback_started",
      `Started playing ${currentTrack.title}`,
    );
    void publishBroadcastState({
      track_id: currentTrack.id,
      is_playing: true,
      position_seconds: audioElements[index].current?.currentTime ?? 0,
    });
  };

  const handleAudioPause = (index: number) => {
    if (suppressedPauseEvents.current.delete(index)) return;
    if (index !== activeAudioIndexRef.current) return;
    if (user?.role !== "admin") {
      setPlaying(false);
      return;
    }
    playbackRequested.current = false;
    if (crossfade.current?.fromIndex === index) cancelCrossfade();
    setPlaying(false);
    const player = audioElements[index].current;
    if (!player || player.ended || !currentTrack) return;
    void recordPlaybackEvent(
      "playback_paused",
      `Paused ${currentTrack.title}`,
    );
    void publishBroadcastState({
      track_id: currentTrack.id,
      is_playing: false,
      position_seconds: player.currentTime,
    });
  };

  const handleAudioTimeUpdate = (index: number) => {
    if (
      index !== activeAudioIndexRef.current ||
      crossfade.current ||
      user?.role !== "admin" ||
      !playbackClaimedRef.current
    ) return;
    const player = audioElements[index].current;
    const nextTrack = queue[0];
    if (!player || !nextTrack || player.paused || !Number.isFinite(player.duration)) return;
    const remaining = player.duration - player.currentTime;
    if (remaining > 0 && remaining <= CROSSFADE_SECONDS) {
      beginCrossfade(index, nextTrack, remaining * 1000);
    }
  };

  const handleAudioEnded = (index: number) => {
    if (index !== activeAudioIndexRef.current) return;
    const activeTransition = crossfade.current;
    if (activeTransition?.fromIndex === index) {
      if (activeTransition.to.paused) return;
      finishCrossfade();
      return;
    }
    if (user?.role !== "admin" || !playbackClaimedRef.current) {
      setPlaying(false);
      return;
    }
    if (currentTrack) {
      void recordPlaybackEvent(
        "playback_ended",
        `Finished playing ${currentTrack.title}`,
      );
    }
    const nextTrack = queue[0];
    if (nextTrack) {
      playTrack(nextTrack);
      return;
    }
    playbackRequested.current = false;
    setPlaying(false);
    void publishBroadcastState({
      track_id: null,
      is_playing: false,
      position_seconds: 0,
    });
  };

  const handleAudioError = (index: number) => {
    if (user?.role === "admin" && !playbackClaimedRef.current) return;
    const transition = crossfade.current;
    if (transition?.toIndex === index) {
      window.clearInterval(transition.intervalId);
      crossfade.current = null;
      audioTrackIds.current[index] = null;
      setError("The next track could not start for the crossfade.");
      return;
    }
    if (index !== activeAudioIndexRef.current) return;
    playbackRequested.current = false;
    setPlaying(false);
    if (user?.role !== "admin") {
      playbackRequested.current = false;
      setAudioEnabled(false);
      setError("Could not load the live audio on this device.");
      return;
    }
    void recordPlaybackEvent(
      "playback_error",
      `Could not play ${currentTrack?.title ?? "audio"}`,
    );
    void publishBroadcastState({
      track_id: null,
      is_playing: false,
      position_seconds: 0,
    });
  };

  const handleAudioVolumeChange = (index: number, player: HTMLAudioElement) => {
    if (index !== activeAudioIndexRef.current || crossfade.current) return;
    volumeRef.current = player.volume;
  };

  const trackCategories = Array.from(new Set([
    ...TRACK_CATEGORY_OPTIONS.map((category) => category.value),
    ...tracks.map((track) => track.category),
  ]));
  const filteredTracks = tracks.filter((track) =>
    `${track.title} ${track.artist} ${track.file_name}`
      .toLocaleLowerCase()
      .includes(search.toLocaleLowerCase()),
  ).filter((track) =>
    selectedTrackCategory === null || track.category === selectedTrackCategory,
  );
  const suggestedTrack = queue[0] ?? null;
  const queuedTrackIds = new Set(queue.map((track) => track.id));
  const title =
    view === "admin-dashboard"
      ? "Admin dashboard"
      : view === "applications"
        ? "DJ applications"
        : view === "dj-management"
          ? "DJ management"
        : view === "ad-applications"
          ? "Ad requests"
          : view === "live-ads"
            ? "Ad operations"
            : view === "dashboard"
              ? "Broadcast overview"
              : view === "library"
                ? "Music library"
                : "Activity log";
  const displayedPlaybackPosition =
    playbackClaimedRef.current
      ? activeAudioPlayer()?.currentTime ?? synchronizedPosition(broadcastState)
      : synchronizedPosition(broadcastState);
  const isAdmin = user?.role === "admin";

  if (!authReady) {
    return <div className="portal-loading">Connecting to WAO FM...</div>;
  }

  if (user?.must_change_password) {
    return (
      <PasswordChangeScreen
        fullName={user.full_name}
        busy={busy}
        error={error}
        onSubmit={handlePasswordChange}
        onLogout={() => void handleLogout()}
      />
    );
  }

  return (
    <div className={`app-shell ${user ? "dj-app-shell" : "viewer-app-shell"}`}>
      {user && (
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={() => setView(user.role === "admin" ? "admin-dashboard" : "dashboard")}
        >
          <span className="brand-mark">K</span>
          <span className="brand-copy">
            <strong>KASTIGO</strong>
            <small>LIVE BROADCASTER</small>
          </span>
        </a>

        <div className="station-card">
          <span className="station-label">ON AIR FREQUENCY</span>
          <strong>88.3 <small>FM</small></strong>
          <span className="station-name">WAO FM RADIO KASTIGO</span>
        </div>

        <span className="nav-caption">WORKSPACE</span>
        <nav className="nav-list" aria-label="Main navigation">
          {navigation
            .filter((item) => {
              const adminOnly = ["admin-dashboard", "applications", "dj-management", "ad-applications", "live-ads"].includes(item.id);
              return !adminOnly || user.role === "admin";
            })
            .map((item) => (
            <button
              className={`nav-item ${view === item.id ? "active" : ""}`}
              key={item.id}
              onClick={() => setView(item.id)}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.id === "dashboard" && user.role === "admin" ? "Live operations" : item.label}
              {item.id === "library" && (
                <span className="nav-count">{tracks.length}</span>
              )}
              {item.id === "dj-management" && (
                <span className="nav-count">{djAccounts.length}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="sidebar-profile">
            <span
              className={`sidebar-avatar${user.role === "admin" ? " is-admin" : ""}`}
              aria-hidden="true"
            >
              {userInitials(user.full_name)}
            </span>
            <div className="sidebar-user">
              <strong>{user.full_name}</strong>
              <span>{user.role === "admin" ? "STATION ADMIN" : "DJ ACCOUNT"}</span>
            </div>
          </div>
          <button className="sidebar-logout" onClick={() => void handleLogout()} disabled={busy}>
            Log Out
          </button>
        </div>
      </aside>
      )}

      <main className={`main-area${user ? "" : " viewer-main-area"}`}>
        {!user && (
          <ListenerPortal
            mode={portalMode}
            hasAdmin={hasAdmin}
            bootstrapAvailable={bootstrapAvailable}
            bootstrapTokenRequired={bootstrapTokenRequired}
            track={currentTrack}
            nextTrack={broadcastState?.next_track ?? null}
            liveAd={liveAd}
            broadcastPlaying={Boolean(broadcastState?.is_playing)}
            audioEnabled={audioEnabled}
            playerMuted={listenerMuted}
            busy={busy}
            error={error}
            notice={notice}
            onModeChange={(mode) => {
              setError("");
              setPortalMode(mode);
            }}
            onEnableAudio={enableLocalAudio}
            onToggleMute={toggleListenerMute}
            onLogin={handleLogin}
            onSignup={handleApplication}
            onBootstrap={handleBootstrap}
            onAdApplication={handleAdApplication}
          />
        )}

        {user && view !== "dashboard" && (
          <header className="topbar">
            <div>
              <div className="breadcrumb">STATION <span>/</span> CONTROL ROOM</div>
              <h1>{title}</h1>
            </div>
            <div className="topbar-status">
              <span className={`status-dot ${health ? "online" : ""}`} />
              <span>{health ? "API CONNECTED" : "API OFFLINE"}</span>
              <span className="topbar-divider" />
              <span className="local-label">LOCAL</span>
            </div>
          </header>
        )}

        {user && (error || notice) && (
          <div className="notification-stack">
            {error && (
              <div className="alert alert-error" role="alert">
                <span>{error}</span>
                <button onClick={() => setError("")} aria-label="Dismiss error">×</button>
              </div>
            )}
            {notice && (
              <div className="alert alert-success" role="status">
                <span>{notice}</span>
                <button onClick={() => setNotice("")} aria-label="Dismiss message">×</button>
              </div>
            )}
          </div>
        )}

        {user?.role === "admin" && view === "admin-dashboard" && (
          <section className="page-content admin-dashboard-page">
            <div className="section-intro">
              <div>
                <p className="eyebrow">SINGLE STATION ADMIN</p>
                <h2>Admin control center</h2>
                <p className="welcome-copy">
                  Review access requests and manage the local broadcast control room.
                </p>
              </div>
              <span className="event-total">ADMINISTRATOR</span>
            </div>

            <section className="panel admin-server-panel">
              <div className="admin-server-status">
                <span className={`status-dot ${health ? "online" : ""}`} />
                <div>
                  <p className="eyebrow">LOCAL SERVER STATUS</p>
                  <strong>{health ? "API connected · SQLite ready" : "API unavailable"}</strong>
                  <span>
                    {health
                      ? `${health.track_count} music tracks · this PC only`
                      : "Check that the local FastAPI server is running."}
                  </span>
                </div>
              </div>
              <div className="admin-current-track">
                <span className={`status-dot ${broadcastState?.is_playing ? "online" : ""}`} />
                <div>
                  <p className="eyebrow">ON AIR</p>
                  <strong>
                    {broadcastState?.is_playing
                      ? currentTrack?.title ?? "Audio is playing"
                      : "Standby"}
                  </strong>
                  <span>
                    {broadcastState?.is_playing
                      ? currentTrack?.artist ?? "WAO FM RADIO KASTIGO"
                      : "No active local player"}
                  </span>
                </div>
              </div>
            </section>

            <div className="admin-action-grid">
              <button className="admin-action-card" onClick={() => setView("applications")}>
                <span>DJ ACCESS</span>
                <strong>{applications.length} pending DJ applications</strong>
                <small>Approve DJs and issue first-login credentials</small>
              </button>
              <button className="admin-action-card" onClick={() => setView("ad-applications")}>
                <span>ADVERTISING</span>
                <strong>{adApplications.length} pending ad requests</strong>
                <small>Review advertiser contact and campaign details</small>
              </button>
              <button className="admin-action-card" onClick={() => setView("live-ads")}>
                <span>LIVE ADVERTISING</span>
                <strong>Manage on-air promotions</strong>
                <small>Publish a moving text banner and listener-page image</small>
              </button>
              <button className="admin-action-card admin-live-action" onClick={() => setView("dashboard")}>
                <span>LIVE OPERATIONS</span>
                <strong>Open the broadcast desk</strong>
                <small>Control the local player, playlist, and music library</small>
              </button>
            </div>
            <p className="admin-local-note">
              The admin player on this PC controls the shared on-air feed for DJ and listener devices on the local network.
            </p>
          </section>
        )}

        <section className="page-content console-page" hidden={!user || view !== "dashboard"}>
            <div className="console-decks">
              <section className="console-deck next-deck" key="next-playlist">
                <div className="deck-header">
                  <span className="deck-label"><b>A</b> NEXT PLAYLIST</span>
                  <span className="next-track-number">
                    {queue.length ? `${queue.length} ${queue.length === 1 ? "TRACK" : "TRACKS"}` : "EMPTY"}
                  </span>
                </div>
                {suggestedTrack ? (
                  <>
                    <div className="next-track-card">
                      <div className="next-track-art"><span>♫</span></div>
                      <div className="deck-track-copy">
                        <small>NEXT TRACK IN PLAYLIST</small>
                        <DeckTrackTitle text={suggestedTrack.title} />
                        <span>{suggestedTrack.artist}</span>
                      </div>
                    </div>
                    <div className="next-track-details">
                      <span>FILE <b>{suggestedTrack.file_name}</b></span>
                      <span>SIZE <b>{formatSize(suggestedTrack.size_bytes)}</b></span>
                    </div>
                    {isAdmin ? (
                      <button className="button button-outline next-play-button" onClick={() => playTrack(suggestedTrack)}>
                        <span>▶</span> {currentTrack ? "Play now" : "Start playlist"}
                      </button>
                    ) : (
                      <p className="deck-hint">Only the station admin can start or pause on-air playback.</p>
                    )}
                    <p className="deck-hint">
                      {currentTrack
                        ? "Queued tracks play in order when the current track ends."
                        : "Start the playlist to play queued tracks in order."}
                    </p>
                  </>
                ) : (
                  <EmptyState
                    title="No next track yet"
                    message="Add a song from Music Library to build the playlist."
                    action={() => setView("library")}
                    actionLabel="Open music library"
                  />
                )}
              </section>

              <section className="console-deck on-air-deck live-player-deck" key="live-player">
                <div className="deck-header">
                  <span className="deck-label"><b>B</b> LIVE PLAYER</span>
                  <span className={`deck-state ${broadcastState?.is_playing ? "deck-state-playing" : ""}`}>
                    <i /> {playing ? "PLAYING" : broadcastState?.is_playing ? "REMOTE ON AIR" : "STANDBY"}
                  </span>
                </div>
                <div className="deck-track">
                  <div className={`deck-record ${playing ? "spinning" : ""}`}>
                    <span>K</span>
                  </div>
                  <div className="deck-track-copy">
                    <small>NOW PLAYING</small>
                    <DeckTrackTitle text={currentTrack?.title ?? "No track loaded"} />
                    <span>{currentTrack?.artist ?? "Select a track from your library"}</span>
                  </div>
                  {!currentTrack && (
                    <button className="button button-outline" onClick={() => setView("library")}>
                      Choose track
                    </button>
                  )}
                </div>
                <div className="deck-waveform" aria-label={playing ? "Browser audio is playing" : "Browser audio is idle"}>
                  {Array.from({ length: 68 }, (_, index) => (
                    <span
                      key={index}
                      className={playing ? "deck-wave-active" : ""}
                      style={{ height: `${14 + ((index * 23 + 9) % 76)}%` }}
                    />
                  ))}
                </div>
                <div className="deck-time-display">
                  <span>PLAYBACK TIME</span>
                  <time>
                    {formatDuration(displayedPlaybackPosition)}
                    {" / "}
                    {currentTrack?.duration_seconds
                      ? formatDuration(currentTrack.duration_seconds)
                      : "--:--"}
                  </time>
                </div>
                {!isAdmin && (
                  <div className="local-audio-monitor">
                    <button
                      className="button button-quiet"
                      onClick={enableLocalAudio}
                      disabled={!currentTrack || audioEnabled}
                    >
                      {audioEnabled ? "Audio enabled" : "Enable live audio"}
                    </button>
                    <span>
                      {audioEnabled
                        ? "Following the admin's on-air player"
                        : "Press once to allow audio on this device"}
                    </span>
                  </div>
                )}
                {audioElements.map((playerRef, index) => (
                  <audio
                    key={index}
                    ref={playerRef}
                    className="audio-player"
                    crossOrigin="use-credentials"
                    controls={isAdmin && index === activeAudioIndex}
                    hidden={index !== activeAudioIndex}
                    preload="none"
                    onPlay={() => handleAudioPlay(index)}
                    onPause={() => handleAudioPause(index)}
                    onTimeUpdate={() => handleAudioTimeUpdate(index)}
                    onEnded={() => handleAudioEnded(index)}
                    onError={() => handleAudioError(index)}
                    onVolumeChange={(event) =>
                      handleAudioVolumeChange(index, event.currentTarget)
                    }
                  />
                ))}
                <div className="deck-footer">
                  <span>PLAYLIST <b>AUTO-NEXT ENABLED</b></span>
                  <span>OUTPUT <b>BROWSER ONLY</b></span>
                </div>
              </section>

              <section className="console-deck listener-deck" key="listener-view">
                <div className="deck-header">
                  <span className="deck-label"><b>C</b> ON-AIR PROMOTION</span>
                  <span className="listener-preview-badge">
                    {liveAdImageCount || liveAd?.text ? "PROMOTION LIVE" : "NO PROMOTION"}
                  </span>
                </div>
                <div className="listener-promo-preview">
                  {currentPromoImage ? (
                    <img
                      key={currentPromoImage.id}
                      className="listener-promo-image"
                      src={apiUrl(currentPromoImage.url)}
                      alt={`On-air promotion ${promoImageIndex + 1} of ${liveAdImageCount}`}
                    />
                  ) : (
                    <div className="listener-promo-image listener-promo-placeholder">
                      NO PROMOTION PHOTO
                    </div>
                  )}
                  <div className="listener-promo-copy">
                    <div className="listener-preview-track">
                      <small>NOW PLAYING</small>
                      <strong>{currentTrack?.title ?? "No track playing"}</strong>
                      <span>{currentTrack?.artist ?? "Waiting for live music"}</span>
                    </div>
                    <div className="listener-promo-message">
                      <small>LIVE PROMOTION TEXT</small>
                      <p>{liveAd?.text || "No live promotion text published."}</p>
                    </div>
                  </div>
                </div>
              </section>
            </div>

            <div className="console-workspace">
              <section className="panel console-playlist-panel">
                <div className="console-panel-heading">
                  <div>
                    <p className="eyebrow">PLAY NEXT QUEUE</p>
                    <h3>Playlist <span>{queue.length}</span></h3>
                  </div>
                </div>
                {queue.length === 0 ? (
                  <EmptyState
                    title="Playlist is empty"
                    message="Add songs with the + button in Music Library."
                  />
                ) : (
                  <>
                    <div className="playlist-list-heading">
                      <span>TRACK</span>
                      <span>TIME</span>
                      <span className="sr-only">ACTIONS</span>
                    </div>
                    <div className="track-list console-track-list">
                      {queue.map((track, index) => (
                        <div
                          key={track.id}
                          className={`track-row playlist-track-row ${index === 0 ? "queue-next-row" : ""}`}
                        >
                          <span className="queue-track-position">{index + 1}</span>
                          <div className="track-row-copy">
                            <strong>
                              {track.title}
                              {index === 0 && <span className="queue-up-next">UP NEXT</span>}
                            </strong>
                            <span>{track.artist} <i>·</i> {formatSize(track.size_bytes)}</span>
                          </div>
                          <TrackDuration track={track} />
                          <button
                            className="queue-next-action"
                            disabled={index === 0}
                            onClick={() => playTrackNext(track)}
                            aria-label={index === 0 ? `${track.title} is next` : `Play ${track.title} next`}
                            title={index === 0 ? "Already next" : "Play next"}
                          >
                            ⏭
                          </button>
                          {isAdmin && (
                            <button
                              className="track-play-action"
                              onClick={() => playTrack(track)}
                              aria-label={`Play ${track.title} now`}
                              title="Play now"
                            >
                              ▶
                            </button>
                          )}
                          <button
                            className="row-action queue-remove-action"
                            onClick={() => removeFromQueue(track)}
                            aria-label={`Remove ${track.title} from playlist`}
                            title="Remove from playlist"
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </section>

              <section className="panel console-full-library-panel">
                <div className="console-panel-heading">
                  <div>
                    <p className="eyebrow">MUSIC LIBRARY</p>
                    <h3>
                      {selectedTrackCategory === null
                        ? "All tracks"
                        : formatTrackCategory(selectedTrackCategory)}
                      {" "}<span>{filteredTracks.length}</span>
                    </h3>
                  </div>
                  <div className="console-library-tools">
                    <button
                      className="category-menu-button"
                      type="button"
                      onClick={() => setCategoryPickerOpen(true)}
                      aria-label="Choose a music library category"
                    >
                      <span aria-hidden="true">☰</span>
                      {selectedTrackCategory === null
                        ? "Categories"
                        : formatTrackCategory(selectedTrackCategory)}
                    </button>
                    <label className="console-search">
                      <span aria-hidden="true">⌕</span>
                      <input
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        placeholder="Search music..."
                        aria-label="Search music"
                      />
                    </label>
                  </div>
                </div>
                {loading ? (
                  <p className="empty-copy">Loading music...</p>
                ) : filteredTracks.length === 0 ? (
                  <EmptyState
                    title={search ? "No tracks found" : "Your library is empty"}
                    message={
                      search
                        ? "Try another title or artist."
                        : "Add songs from your computer to begin."
                    }
                    action={search ? undefined : () => setUploadOpen(true)}
                    actionLabel="Add first track"
                  />
                ) : (
                  <div className="track-list console-track-list">
                    {filteredTracks.map((track) => (
                      <TrackRow
                        key={track.id}
                        track={track}
                        selected={currentTrack?.id === track.id}
                        onAddToQueue={addToQueue}
                        onPlayNow={playTrack}
                        canControlPlayback={isAdmin}
                        canDelete={isAdmin}
                        queued={queuedTrackIds.has(track.id)}
                        onDelete={handleDelete}
                      />
                    ))}
                  </div>
                )}
              </section>

              <section className="panel console-history-panel">
                <div className="console-panel-heading">
                  <div>
                    <p className="eyebrow">PLAYBACK HISTORY</p>
                    <h3>Recent activity <span>{events.length}</span></h3>
                  </div>
                  <button className="text-button" onClick={() => setView("activity")}>
                    View log <span>→</span>
                  </button>
                </div>
                <div className="console-history-list">
                  <ActivityRows events={events.slice(0, 6)} />
                </div>
              </section>
            </div>
          </section>

        {user && view === "library" && (
          <section className="page-content library-page">
            <div className="section-intro">
              <div>
                <p className="eyebrow">FILE AND PLAY YOUR AUDIO</p>
                <h2>Your music library</h2>
                <p className="welcome-copy">
                  Audio files are saved locally and streamed by your local API.
                </p>
              </div>
              <button className="button button-primary" onClick={() => setUploadOpen(true)}>
                <span className="button-plus">+</span> Add music
              </button>
            </div>
            <section className="panel full-panel">
              <div className="library-toolbar">
                <div>
                  <h3>
                    {selectedTrackCategory === null
                      ? "All tracks"
                      : formatTrackCategory(selectedTrackCategory)}
                    <span className="subtle-count">{filteredTracks.length}</span>
                  </h3>
                  <p>Your local collection</p>
                </div>
                <div className="library-tools">
                  <button
                    className="category-menu-button"
                    type="button"
                    onClick={() => setCategoryPickerOpen(true)}
                    aria-label="Choose a music library category"
                  >
                    <span aria-hidden="true">☰</span>
                    {selectedTrackCategory === null
                      ? "Categories"
                      : formatTrackCategory(selectedTrackCategory)}
                  </button>
                  <label className="search-box">
                    <span aria-hidden="true">⌕</span>
                    <input
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="Search music..."
                      aria-label="Search music"
                    />
                  </label>
                </div>
              </div>
              {loading ? (
                <p className="empty-copy">Loading your library...</p>
              ) : filteredTracks.length === 0 ? (
                <EmptyState
                  title={
                    search
                      ? "No matches found"
                      : selectedTrackCategory !== null
                        ? `No ${formatTrackCategory(selectedTrackCategory).toLowerCase()} tracks yet`
                        : "Your library is empty"
                  }
                  message={
                    search
                      ? "Try another title or artist name."
                      : selectedTrackCategory !== null
                        ? "Choose another category or upload a folder with this name."
                        : "Choose a folder containing MP3, WAV, FLAC, M4A, OGG, or AAC audio."
                  }
                  action={search ? undefined : () => setUploadOpen(true)}
                  actionLabel="Add music folder"
                />
              ) : (
                <div className="table-scroll">
                  <table className="track-table">
                    <thead>
                      <tr>
                        <th>TRACK</th>
                        <th>FILE</th>
                        <th>SIZE</th>
                        <th>ADDED</th>
                        <th><span className="sr-only">ACTIONS</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTracks.map((track) => (
                        <TrackRow
                          key={track.id}
                          track={track}
                          selected={currentTrack?.id === track.id}
                          onAddToQueue={addToQueue}
                          onPlayNow={playTrack}
                          canControlPlayback={isAdmin}
                          canDelete={isAdmin}
                          queued={queuedTrackIds.has(track.id)}
                          onDelete={handleDelete}
                          tableRow
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </section>
        )}

        {user && view === "activity" && (
          <section className="page-content activity-page">
            <div className="section-intro">
              <div>
                <p className="eyebrow">LOCAL PLAYBACK HISTORY</p>
                <h2>Activity log</h2>
                <p className="welcome-copy">
                  Playback events are stored in the local SQLite database.
                </p>
              </div>
              <span className="event-total">{events.length} EVENTS</span>
            </div>
            <section className="panel full-panel">
              <div className="panel-heading activity-heading">
                <div>
                  <p className="eyebrow">LATEST FIRST</p>
                  <h3>Recent events</h3>
                </div>
              </div>
              <RecentActivity events={events} />
            </section>
            <div className="info-note">
              <span className="info-mark">i</span>
              <p>
                This log tracks audio started, paused, ended, or errored in this browser.
                It does not measure Windows audio input or OBS broadcast status.
              </p>
            </div>
          </section>
        )}

        {user && view === "applications" && (
          <section className="page-content applications-page">
            <div className="section-intro">
              <div>
                <p className="eyebrow">STATION ACCESS</p>
                <h2>DJ applications</h2>
                <p className="welcome-copy">
                  Approve applicants and give them their one-time temporary credentials.
                </p>
              </div>
              <span className="event-total">{applications.length} PENDING</span>
            </div>

            {approvedDj && (
              <section className="panel credentials-panel" role="status">
                <button
                  className="close-button"
                  onClick={() => setApprovedDj(null)}
                  aria-label="Dismiss temporary credentials"
                >
                  ×
                </button>
                <p className="eyebrow">GIVE THESE CREDENTIALS TO THE DJ</p>
                <h3>{approvedDj.user.full_name} was approved</h3>
                <p>This temporary password is shown once. The DJ must change it after signing in.</p>
                <div className="credential-fields">
                  <span>USERNAME <b>{approvedDj.user.username}</b></span>
                  <span>TEMPORARY PASSWORD <b>{approvedDj.temporary_password}</b></span>
                </div>
              </section>
            )}

            <section className="panel applications-list-panel">
              {applications.length === 0 ? (
                <EmptyState
                  title="No pending DJ applications"
                  message="New applications from the listener page will appear here."
                />
              ) : (
                <div className="application-list">
                  {applications.map((application) => (
                    <article className="application-card" key={application.id}>
                      <div className="application-details">
                        <div>
                          <h3>{application.full_name}</h3>
                          <a href={`mailto:${application.email}`}>{application.email}</a>
                          <time>{formatDate(application.submitted_at)}</time>
                        </div>
                        <p>{application.experience}</p>
                      </div>
                      <form
                        className="application-actions"
                        onSubmit={(event) => {
                          event.preventDefault();
                          const form = new FormData(event.currentTarget);
                          void handleApproveApplication(
                            application.id,
                            String(form.get("username") ?? ""),
                          );
                        }}
                      >
                        <label className="form-field">
                          <span>ASSIGN USERNAME</span>
                          <input
                            name="username"
                            defaultValue={suggestUsername(application.full_name)}
                            minLength={3}
                            maxLength={30}
                            required
                          />
                        </label>
                        <div>
                          <button className="button button-primary">Approve & create DJ account</button>
                          <button
                            className="button button-quiet"
                            type="button"
                            onClick={() => void handleRejectApplication(application.id)}
                          >
                            Reject
                          </button>
                        </div>
                      </form>
                    </article>
                  ))}
                </div>
              )}
            </section>
          </section>
        )}

        {user && view === "dj-management" && user.role === "admin" && (
          <section className="page-content dj-management-page">
            <div className="section-intro">
              <div>
                <p className="eyebrow">STATION ACCESS</p>
                <h2>DJ management</h2>
                <p className="welcome-copy">
                  Ban accounts to revoke access temporarily, or delete an account permanently.
                </p>
              </div>
              <span className="event-total">{djAccounts.length} DJ ACCOUNTS</span>
            </div>

            <div className="dj-account-stats">
              <article>
                <span>TOTAL DJ ACCOUNTS</span>
                <strong>{djAccounts.length}</strong>
              </article>
              <article>
                <span>ACTIVE</span>
                <strong>{djAccounts.filter((account) => !account.is_banned).length}</strong>
              </article>
              <article>
                <span>BANNED</span>
                <strong>{djAccounts.filter((account) => account.is_banned).length}</strong>
              </article>
            </div>

            <section className="panel dj-account-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">DJ ACCOUNTS</p>
                  <h3>Station access list</h3>
                </div>
              </div>
              {djAccountsLoading ? (
                <p className="empty-copy">Loading DJ accounts...</p>
              ) : djAccounts.length === 0 ? (
                <EmptyState
                  title="No DJ accounts yet"
                  message="Approved DJs will appear here. Review new requests under DJ applications."
                  action={() => setView("applications")}
                  actionLabel="View DJ applications"
                />
              ) : (
                <div className="dj-account-list">
                  {djAccounts.map((account) => (
                    <article
                      className={`dj-account-row${account.is_banned ? " is-banned" : ""}`}
                      key={account.id}
                    >
                      <div className="dj-account-details">
                        <div className="dj-account-heading">
                          <h3>{account.full_name}</h3>
                          <span className={`dj-account-status${account.is_banned ? " is-banned" : ""}`}>
                            {account.is_banned ? "BANNED" : "ACTIVE"}
                          </span>
                        </div>
                        <span className="dj-account-username">@{account.username}</span>
                        {account.email && <a href={`mailto:${account.email}`}>{account.email}</a>}
                        <time>Created {formatDate(account.created_at)}</time>
                      </div>
                      <div className="dj-account-actions">
                        <button
                          className={`button ${account.is_banned ? "button-primary" : "button-quiet"}`}
                          disabled={busy}
                          onClick={() => void handleToggleDjBan(account)}
                        >
                          {account.is_banned ? "Restore access" : "Ban account"}
                        </button>
                        <button
                          className="button button-quiet dj-delete-button"
                          disabled={busy}
                          onClick={() => void handleDeleteDj(account)}
                        >
                          Delete account
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
          </section>
        )}

        {user && view === "ad-applications" && user.role === "admin" && (
          <section className="page-content applications-page">
            <div className="section-intro">
              <div>
                <p className="eyebrow">ADVERTISING</p>
                <h2>Ad requests</h2>
                <p className="welcome-copy">
                  Review advertisers’ contact details and campaign requests.
                </p>
              </div>
              <span className="event-total">{adApplications.length} PENDING</span>
            </div>
            <section className="panel applications-list-panel">
              {adApplications.length === 0 ? (
                <EmptyState
                  title="No pending ad requests"
                  message="Requests submitted from the listener page will appear here."
                />
              ) : (
                <div className="application-list">
                  {adApplications.map((application) => (
                    <article className="application-card ad-application-card" key={application.id}>
                      <div className="application-details">
                        <div>
                          <h3>{application.business_name || application.contact_name}</h3>
                          {application.business_name && (
                            <span className="ad-contact-name">Contact: {application.contact_name}</span>
                          )}
                          <a href={`mailto:${application.email}`}>{application.email}</a>
                          {application.phone && (
                            <a href={`tel:${application.phone}`}>{application.phone}</a>
                          )}
                          <time>{formatDate(application.submitted_at)}</time>
                        </div>
                        <p>{application.ad_details}</p>
                      </div>
                      <div className="application-actions">
                        <button
                          className="button button-primary"
                          onClick={() => void handleReviewAdApplication(application.id)}
                        >
                          Mark reviewed
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
          </section>
        )}

        {user && view === "live-ads" && user.role === "admin" && (
          <section className="page-content live-ad-page">
            <div className="section-intro">
              <div>
                <p className="eyebrow">LIVE ADVERTISING</p>
                <h2>Ad operations</h2>
                <p className="welcome-copy">
                  Text scrolls across the listener screen; an optional image appears in its ad space.
                </p>
              </div>
              <span className="event-total">
                {liveAd?.text || liveAd?.images.length ? "ON AIR" : "NO ACTIVE AD"}
              </span>
            </div>

            <div className="live-ad-grid">
              <form className="panel live-ad-form" onSubmit={(event) => void handlePublishLiveAd(event)}>
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">WORKSPACE</p>
                    <h3>Publish promotion</h3>
                  </div>
                </div>
                <label className="form-field">
                  <span>SCROLLING AD TEXT <small>OPTIONAL · MAX 1000 CHARACTERS</small></span>
                  <textarea
                    name="text"
                    rows={4}
                    maxLength={1000}
                    value={adText}
                    onChange={(event) => setAdText(event.target.value)}
                    placeholder="Type the message to scroll across the live screen..."
                  />
                </label>
                <div className="form-field">
                  <span>AD PHOTOS / BANNERS <small>OPTIONAL · UP TO 50 · JPG, PNG, WEBP, GIF, BMP, TIFF, HEIC OR AVIF · 5 MB EACH</small></span>
                  <input
                    ref={adImageInput}
                    type="file"
                    className="sr-only"
                    aria-label="Select ad photos"
                    accept="image/*"
                    multiple
                    disabled={removeAdImages}
                    onChange={(event) => {
                      const addedImages = Array.from(event.currentTarget.files ?? []);
                      const totalCount = (liveAd?.images.length ?? 0) + selectedAdImages.length + addedImages.length;
                      event.currentTarget.value = "";
                      if (totalCount > MAX_AD_IMAGES) {
                        setError(`The slideshow can contain no more than ${MAX_AD_IMAGES} photos. Remove some or select fewer.`);
                        return;
                      }
                      setError("");
                      setSelectedAdImages((current) => [...current, ...addedImages]);
                      setRemoveAdImages(false);
                    }}
                  />
                  <div className="live-ad-actions">
                    <button
                      className="button button-quiet"
                      type="button"
                      disabled={busy || removeAdImages || (liveAd?.images.length ?? 0) + selectedAdImages.length >= MAX_AD_IMAGES}
                      onClick={() => adImageInput.current?.click()}
                    >
                      {liveAd?.images.length || selectedAdImages.length ? "Add more photos" : "Add photos"}
                    </button>
                    {selectedAdImages.length > 0 && (
                      <button
                        className="button button-quiet"
                        type="button"
                        disabled={busy}
                        onClick={() => setSelectedAdImages([])}
                      >
                        Clear selected
                      </button>
                    )}
                  </div>
                </div>
                {selectedAdImages.length > 0 && (
                  <p className="live-ad-help">
                    {selectedAdImages.length} new photo{selectedAdImages.length === 1 ? "" : "s"} selected. Publishing adds them to the slideshow ({(liveAd?.images.length ?? 0) + selectedAdImages.length} of {MAX_AD_IMAGES}).
                  </p>
                )}
                {liveAd?.images.length ? (
                  <label className="live-ad-remove-image">
                    <input
                      name="remove_images"
                      type="checkbox"
                      checked={removeAdImages}
                      disabled={selectedAdImages.length > 0}
                      onChange={(event) => setRemoveAdImages(event.target.checked)}
                    />
                    Remove all current photos when publishing
                  </label>
                ) : null}
                <p className="live-ad-help">
                  Publish text, photos, or both. Add more photos to extend the current slideshow; each displays for 5 seconds and fills the ad space. “Apply for ads” remains separate on the listener page.
                </p>
                <div className="live-ad-actions">
                  <button className="button button-primary" disabled={busy}>
                    {busy ? "Publishing..." : "Publish live ad"}
                  </button>
                  <button
                    className="button button-quiet"
                    type="button"
                    disabled={busy || (!liveAd?.text && !liveAd?.images.length)}
                    onClick={() => void handleClearLiveAd()}
                  >
                    Stop current ad
                  </button>
                </div>
              </form>

              <section className="panel live-ad-preview">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">LISTENER PREVIEW</p>
                    <h3>On-air promotion</h3>
                  </div>
                </div>
                {liveAd?.images.length ? (
                  <img src={apiUrl(liveAd.images[0].url)} alt="First image in the live advertisement slideshow" />
                ) : (
                  <div className="live-ad-image-placeholder">AD IMAGE SPACE</div>
                )}
                {liveAd?.images.length ? (
                  <div className="live-ad-gallery" aria-label={`${liveAd.images.length} active advertisement images`}>
                    {liveAd.images.map((image, index) => (
                      <img key={image.id} src={apiUrl(image.url)} alt={`Ad banner ${index + 1}`} />
                    ))}
                  </div>
                ) : null}
                <div className="live-ad-text-preview">
                  <span>SCROLLING TEXT</span>
                  <strong>{liveAd?.text || "No scrolling text published."}</strong>
                </div>
              </section>
            </div>
          </section>
        )}

        {user && view !== "dashboard" && (
          <footer className="page-footer">
            <span>WAO FM RADIO KASTIGO <span className="footer-dot">·</span> 88.3 FM</span>
            <span>LOCAL CONTROL ROOM</span>
          </footer>
        )}
      </main>

      {user && categoryPickerOpen && (
        <div
          className="modal-backdrop category-modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setCategoryPickerOpen(false);
          }}
        >
          <section
            className="category-picker-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="category-picker-title"
          >
            <div className="modal-heading">
              <div>
                <p className="eyebrow">MUSIC LIBRARY</p>
                <h2 id="category-picker-title">Choose a category</h2>
              </div>
              <button
                className="close-button"
                onClick={() => setCategoryPickerOpen(false)}
                aria-label="Close category picker"
              >
                ×
              </button>
            </div>
            <div className="category-picker-options">
              <button
                className={selectedTrackCategory === null ? "selected" : ""}
                onClick={() => {
                  setSelectedTrackCategory(null);
                  setCategoryPickerOpen(false);
                }}
              >
                <span>All categories</span>
                <strong>{tracks.length}</strong>
              </button>
              {trackCategories.map((category) => {
                const count = tracks.filter((track) => track.category === category).length;
                return (
                  <button
                    key={category}
                    className={selectedTrackCategory === category ? "selected" : ""}
                    onClick={() => {
                      setSelectedTrackCategory(category);
                      setCategoryPickerOpen(false);
                    }}
                  >
                    <span>{formatTrackCategory(category)}</span>
                    <strong>{count}</strong>
                  </button>
                );
              })}
            </div>
          </section>
        </div>
      )}

      {user && uploadOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setUploadOpen(false);
          }}
        >
          <section className="upload-modal" role="dialog" aria-modal="true" aria-labelledby="upload-title">
            <div className="modal-heading">
              <div>
                <p className="eyebrow">LOCAL MUSIC LIBRARY</p>
                <h2 id="upload-title">Add music</h2>
              </div>
              <button className="close-button" onClick={() => setUploadOpen(false)} aria-label="Close upload dialog">×</button>
            </div>
            <form onSubmit={handleUpload}>
              <div className="upload-mode-options" role="group" aria-label="Choose upload type">
                <button
                  type="button"
                  className={uploadMode === "file" ? "selected" : ""}
                  aria-pressed={uploadMode === "file"}
                  disabled={busy}
                  onClick={() => {
                    if (fileInput.current) fileInput.current.value = "";
                    setUploadMode("file");
                  }}
                >
                  Single file
                </button>
                <button
                  type="button"
                  className={uploadMode === "folder" ? "selected" : ""}
                  aria-pressed={uploadMode === "folder"}
                  disabled={busy}
                  onClick={() => {
                    if (fileInput.current) fileInput.current.value = "";
                    setUploadMode("folder");
                  }}
                >
                  Folder
                </button>
              </div>
              <label className="file-drop">
                <span className="upload-icon">↑</span>
                <strong>
                  {uploadMode === "folder" ? "Choose a folder of audio files" : "Choose one audio file"}
                </strong>
                <span>
                  {uploadMode === "folder"
                    ? "The folder name becomes the category · Up to 250 MB per file"
                    : "MP3, WAV, FLAC, M4A, OGG, AAC · Up to 250 MB"}
                </span>
                <input
                  ref={fileInput}
                  type="file"
                  name={uploadMode === "folder" ? "files" : "file"}
                  accept=".mp3,.wav,.flac,.m4a,.ogg,.aac,audio/*"
                  multiple={uploadMode === "folder"}
                  disabled={busy}
                  required
                />
              </label>
              {uploadMode === "file" && (
                <label className="form-field">
                  <span>CATEGORY</span>
                  <select
                    value={singleUploadCategory}
                    onChange={(event) => setSingleUploadCategory(event.target.value)}
                  >
                    {trackCategories.map((category) => (
                      <option key={category} value={category}>
                        {formatTrackCategory(category)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <p className="upload-folder-help">
                {uploadMode === "folder"
                  ? "Supported audio: MP3, WAV, FLAC, M4A, OGG, AAC. Duplicate audio is skipped automatically."
                  : "The file name supplies the track title and the artist defaults to Unknown Artist. Duplicate audio is rejected."}
              </p>
              <div className="modal-actions">
                <button type="button" className="button button-quiet" disabled={busy} onClick={() => setUploadOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="button button-primary" disabled={busy}>
                  {busy ? "Uploading..." : uploadMode === "folder" ? "Upload folder" : "Upload file"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}

function TrackRow({
  track,
  selected,
  onAddToQueue,
  onPlayNow,
  canControlPlayback,
  canDelete,
  queued,
  onDelete,
  tableRow = false,
}: {
  track: Track;
  selected: boolean;
  onAddToQueue: (track: Track) => void;
  onPlayNow: (track: Track) => void;
  canControlPlayback: boolean;
  canDelete: boolean;
  queued: boolean;
  onDelete: (track: Track) => void;
  tableRow?: boolean;
}) {
  if (tableRow) {
    return (
      <tr className={selected ? "selected-row" : ""}>
        <td>
          <div className="table-track-cell">
            <button
              className={`track-cover ${selected ? "selected-cover" : ""} ${queued ? "queued-cover" : ""}`}
              onClick={() => onAddToQueue(track)}
              disabled={queued}
              aria-label={queued ? `${track.title} is in playlist` : `Add ${track.title} to playlist`}
              title={queued ? "Already in playlist" : "Add to playlist"}
            >
              {queued ? "✓" : "+"}
            </button>
            <span className="table-track-copy">
              <strong>{track.title}</strong>
              <small>{track.artist} · {formatTrackCategory(track.category)}</small>
            </span>
          </div>
        </td>
        <td className="file-name-cell">{track.file_name}</td>
        <td className="metadata-cell">{formatSize(track.size_bytes)}</td>
        <td className="metadata-cell">{formatDate(track.created_at)}</td>
        <td>
          <div className="table-actions">
            {canControlPlayback && (
              <button
                className="track-play-action"
                onClick={() => onPlayNow(track)}
                aria-label={`Play ${track.title} now`}
                title="Play now"
              >
                ▶
              </button>
            )}
            {canDelete && (
              <button className="row-action" onClick={() => onDelete(track)} aria-label={`Remove ${track.title}`}>×</button>
            )}
          </div>
        </td>
      </tr>
    );
  }
  return (
    <div className="track-row">
      <button
        className={`track-cover ${selected ? "selected-cover" : ""} ${queued ? "queued-cover" : ""}`}
        onClick={() => onAddToQueue(track)}
        disabled={queued}
        aria-label={queued ? `${track.title} is in playlist` : `Add ${track.title} to playlist`}
        title={queued ? "Already in playlist" : "Add to playlist"}
      >
        {queued ? "✓" : "+"}
      </button>
      <div className="track-row-copy">
        <strong>{track.title}</strong>
        <span>{track.artist} <i>·</i> {formatTrackCategory(track.category)} <i>·</i> {formatSize(track.size_bytes)}</span>
      </div>
      <div className="track-row-actions">
        {canControlPlayback && (
          <button
            className="track-play-action"
            onClick={() => onPlayNow(track)}
            aria-label={`Play ${track.title} now`}
            title="Play now"
          >
            ▶
          </button>
        )}
        {canDelete && (
          <button className="row-action" onClick={() => onDelete(track)} aria-label={`Remove ${track.title}`}>×</button>
        )}
      </div>
    </div>
  );
}

function TrackDuration({ track }: { track: Track }) {
  return <time className="playlist-duration">
    {track.duration_seconds === null ? "--:--" : formatDuration(track.duration_seconds)}
  </time>;
}

function EmptyState({
  title,
  message,
  action,
  actionLabel,
}: {
  title: string;
  message: string;
  action?: () => void;
  actionLabel?: string;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">♪</span>
      <strong>{title}</strong>
      <p>{message}</p>
      {action && actionLabel && (
        <button className="text-button empty-action" onClick={action}>{actionLabel} <span>→</span></button>
      )}
    </div>
  );
}

function PasswordChangeScreen({
  fullName,
  busy,
  error,
  onSubmit,
  onLogout,
}: {
  fullName: string;
  busy: boolean;
  error: string;
  onSubmit: (password: string) => void;
  onLogout: () => void;
}) {
  const [validationError, setValidationError] = useState("");

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") ?? "");
    const confirmation = String(form.get("confirmation") ?? "");
    if (password !== confirmation) {
      setValidationError("The passwords do not match.");
      return;
    }
    setValidationError("");
    onSubmit(password);
  };

  return (
    <main className="password-screen">
      <section className="portal-modal password-change-card">
        <p className="viewer-eyebrow">FIRST SIGN-IN</p>
        <h1>Welcome, {fullName}</h1>
        <p className="portal-description">
          Change the temporary password provided by the station admin before entering the control room.
        </p>
        <form className="portal-form" onSubmit={submit}>
          <label>
            <span>NEW PASSWORD <small>12 characters minimum</small></span>
            <input
              name="password"
              type="password"
              autoComplete="new-password"
              minLength={12}
              maxLength={128}
              required
            />
          </label>
          <label>
            <span>CONFIRM NEW PASSWORD</span>
            <input
              name="confirmation"
              type="password"
              autoComplete="new-password"
              minLength={12}
              maxLength={128}
              required
            />
          </label>
          {(error || validationError) && (
            <p className="portal-form-error" role="alert">{error || validationError}</p>
          )}
          <button className="button button-primary" disabled={busy}>
            {busy ? "Updating..." : "Set new password"}
          </button>
        </form>
        <button className="portal-switch" onClick={onLogout}>Log out and return to listener page</button>
      </section>
    </main>
  );
}

function DeckTrackTitle({ text }: { text: string }) {
  const viewportRef = useRef<HTMLSpanElement>(null);
  const textRef = useRef<HTMLSpanElement>(null);
  const [overflowing, setOverflowing] = useState(false);

  useEffect(() => {
    const viewport = viewportRef.current;
    const content = textRef.current;
    if (!viewport || !content) return;

    const measureOverflow = () => {
      setOverflowing(content.scrollWidth > viewport.clientWidth + 1);
    };
    measureOverflow();

    const observer = new ResizeObserver(measureOverflow);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [text]);

  return (
    <strong className="deck-title" title={text}>
      <span
        ref={viewportRef}
        className={`deck-title-marquee${overflowing ? " is-overflowing" : ""}`}
      >
        <span
          className="deck-title-track"
          style={{ animationDuration: `${Math.max(7, text.length * 0.2)}s` }}
        >
          <span ref={textRef}>{text}</span>
          {overflowing && <span aria-hidden="true">{text}</span>}
        </span>
      </span>
    </strong>
  );
}

function ActivityRows({ events }: { events: MonitorEvent[] }) {
  const labels: Record<string, string> = {
    playback_started: "Playback started",
    playback_paused: "Playback paused",
    playback_ended: "Playback ended",
    playback_error: "Playback error",
  };
  if (events.length === 0) {
    return <p className="empty-copy">Playback activity will appear here.</p>;
  }
  return (
    <div className="activity-list">
      {events.map((event) => (
        <div className="activity-row" key={event.id}>
          <span className={`activity-marker ${event.event_type}`} />
          <span className="activity-copy">
            <strong>{labels[event.event_type] ?? "Activity"}</strong>
            <small>{event.track_title ?? event.message}</small>
          </span>
          <time>{formatDate(event.created_at)}</time>
        </div>
      ))}
    </div>
  );
}

function RecentActivity({
  events,
  onViewAll,
}: {
  events: MonitorEvent[];
  onViewAll?: () => void;
}) {
  return (
    <section className="panel activity-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">LOCAL MONITOR</p>
          <h3>Recent activity</h3>
        </div>
        {onViewAll && (
          <button className="text-button" onClick={onViewAll}>View log <span>→</span></button>
        )}
      </div>
      <ActivityRows events={events} />
    </section>
  );
}

export default App;

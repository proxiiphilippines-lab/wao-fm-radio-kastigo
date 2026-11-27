export interface Track {
  id: string;
  title: string;
  artist: string;
  file_name: string;
  content_type: string;
  category: TrackCategory;
  duration_seconds: number | null;
  size_bytes: number;
  created_at: string;
  stream_url: string;
}

export type TrackCategory = string;

export interface MonitorEvent {
  id: number;
  event_type: string;
  message: string;
  track_id: string | null;
  track_title: string | null;
  created_at: string;
}

export interface Health {
  status: string;
  database: string;
  track_count: number;
}

export interface AuthUser {
  id: string;
  username: string;
  full_name: string;
  role: "admin" | "dj";
  must_change_password: boolean;
}

export interface AuthStatus {
  has_admin: boolean;
  user: AuthUser | null;
  bootstrap_available: boolean;
  bootstrap_token_required: boolean;
}

export interface DjApplication {
  id: string;
  full_name: string;
  email: string;
  experience: string;
  submitted_at: string;
}

export interface DjAccount {
  id: string;
  username: string;
  full_name: string;
  email: string;
  is_banned: boolean;
  created_at: string;
}

export interface AdApplication {
  id: string;
  contact_name: string;
  business_name: string;
  email: string;
  phone: string;
  ad_details: string;
  submitted_at: string;
}

export interface LiveAdImage {
  id: string;
  url: string;
}

export interface LiveAd {
  text: string;
  images: LiveAdImage[];
  updated_at: string | null;
}

export interface BroadcastState {
  track: Track | null;
  next_track: Track | null;
  controller_id: string | null;
  is_playing: boolean;
  position_seconds: number;
  revision: number;
  updated_at: string;
}

export interface ApprovedDj {
  user: AuthUser;
  temporary_password: string;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new ApiError(body?.detail ?? `Request failed (${response.status}).`, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  bootstrapAdmin: (data: {
    username: string;
    full_name: string;
    password: string;
    setup_token: string;
  }) =>
    request<AuthUser>("/api/auth/bootstrap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  login: (username: string, password: string) =>
    request<AuthUser>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  changePassword: (new_password: string) =>
    request<AuthUser>("/api/auth/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password }),
    }),
  applyForDj: (data: { full_name: string; email: string; experience: string }) =>
    request<DjApplication>("/api/auth/applications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  applyForAds: (data: {
    contact_name: string;
    business_name: string;
    email: string;
    phone: string;
    ad_details: string;
  }) =>
    request<AdApplication>("/api/public/ad-applications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  djApplications: () => request<DjApplication[]>("/api/admin/applications"),
  djAccounts: () => request<DjAccount[]>("/api/admin/djs"),
  setDjBanned: (id: string, isBanned: boolean) =>
    request<DjAccount>(`/api/admin/djs/${encodeURIComponent(id)}/ban`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_banned: isBanned }),
    }),
  deleteDjAccount: (id: string) =>
    request<void>(`/api/admin/djs/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  adApplications: () => request<AdApplication[]>("/api/admin/ad-applications"),
  publicLiveAd: () => request<LiveAd>("/api/public/live-ad", { cache: "no-store" }),
  publishLiveAd: (data: {
    text: string;
    images: File[];
    remove_images: boolean;
    append_images: boolean;
  }) => {
    const formData = new FormData();
    formData.append("text", data.text);
    for (const image of data.images) formData.append("images", image);
    formData.append("remove_images", String(data.remove_images));
    formData.append("append_images", String(data.append_images));
    return request<LiveAd>("/api/admin/live-ad", {
      method: "PUT",
      body: formData,
    });
  },
  clearLiveAd: () =>
    request<void>("/api/admin/live-ad", { method: "DELETE" }),
  reviewAdApplication: (id: string) =>
    request<void>(`/api/admin/ad-applications/${encodeURIComponent(id)}/review`, {
      method: "POST",
    }),
  approveDjApplication: (id: string, username: string) =>
    request<ApprovedDj>(`/api/admin/applications/${encodeURIComponent(id)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username }),
    }),
  rejectDjApplication: (id: string) =>
    request<void>(`/api/admin/applications/${encodeURIComponent(id)}/reject`, {
      method: "POST",
    }),
  publicBroadcast: () => request<BroadcastState>("/api/public/broadcast"),
    claimBroadcast: (data: {
      controller_id: string;
      track_id: string;
      position_seconds: number;
    }) =>
      request<BroadcastState>("/api/broadcast/claim", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }),
  playlist: () => request<Track[]>("/api/playlist"),
  addPlaylistTrack: (track_id: string) =>
    request<Track[]>("/api/playlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track_id }),
    }),
  playPlaylistTrackNext: (track_id: string) =>
    request<Track[]>("/api/playlist/next", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track_id }),
    }),
  removePlaylistTrack: (trackId: string) =>
    request<Track[]>(`/api/playlist/${encodeURIComponent(trackId)}`, {
      method: "DELETE",
    }),
  setBroadcast: (data: {
    controller_id: string;
    track_id: string | null;
    is_playing: boolean;
    position_seconds: number;
  }) =>
    request<BroadcastState>("/api/broadcast/state", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  tracks: () => request<Track[]>("/api/tracks"),
  events: () => request<MonitorEvent[]>("/api/monitoring/events"),
  upload: (file: File, title: string, artist: string, category: TrackCategory) => {
    const data = new FormData();
    data.append("file", file);
    data.append("title", title);
    data.append("artist", artist);
    data.append("category", category);
    return request<Track>("/api/tracks", { method: "POST", body: data });
  },
  removeTrack: (trackId: string) =>
    request<void>(`/api/tracks/${encodeURIComponent(trackId)}`, {
      method: "DELETE",
    }),
  recordEvent: (event: {
    event_type: string;
    message: string;
    track_id: string | null;
  }) =>
    request<MonitorEvent>("/api/monitoring/events", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event),
    }),
};

/* web/src/api.ts — central API helpers & types
 *
 * Goals:
 * - Work locally (dev) and on Vercel (prod) without same-origin /api issues.
 * - Keep backwards compatibility with older UI code by exporting legacy names
 *   and flexible function signatures.
 *
 * API conventions in this codebase (as used by existing pages/components):
 * - Auth: /api/auth/login, /api/auth/register
 * - Me:   /api/me
 * - User Library: /api/users/{userId}/favorites|not-interested and /api/ratings/ratings
 * - Shows: /api/shows/{tmdbId} and /api/shows/{tmdbId}/posts
 * - Recs:  /api/recs, /api/recs/v2, /api/recs/v3
 * - Discover: /api/discover
 * - Admin: /api/admin/stats, /api/admin/users, etc.
 */

// ───────────────── Types ─────────────────
export type User = {
  id: number;
  email: string;
  username?: string | null;
  is_admin: boolean;
};

export type AdminUser = User & {
  created_at?: string;
  last_login_at?: string | null;
  last_seen_at?: string | null;
  favorites_count: number;
  ratings_count: number;
  not_interested_count: number;
};

export type AdminStats = {
  total_users: number;
  new_users_last_7_days: number;
  total_favorites: number;
  users_with_favorites: number;
  total_ratings: number;
  users_with_ratings: number;
  total_not_interested: number;
  [k: string]: any;
};

export type Show = {
  show_id: number;
  title: string;
  poster_path?: string | null;
  overview?: string | null;
  vote_average?: number | null;
  first_air_date?: string | null;
  [k: string]: any;
};

export type Favorite = {
  user_id: number;
  tmdb_id: number;
  created_at?: string;
  title?: string;
  poster_path?: string | null;
  [k: string]: any;
};

export type WatchlistItem = {
  user_id?: number;
  tmdb_id: number;
  added_at?: string;
  title?: string;
  poster_path?: string | null;
  poster_url?: string | null;
  [k: string]: any;
};

export type UserRating = {
  user_id?: number;
  tmdb_id: number;
  rating: number;
  title?: string | null;
  seasons_completed?: number | null;
  notes?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type NotInterested = {
  user_id: number;
  tmdb_id: number;
  created_at?: string;
  [k: string]: any;
};

export type RecItem = {
  tmdb_id: number;
  title?: string | null;
  score?: number;
  poster_url?: string | null;
  reason?: string;
  [k: string]: any;
};

export type LoginResponse = { access_token: string; token_type?: string };

export type RecsOptions = {
  limit?: number;
  diversify?: boolean;
  debug?: boolean;
  [k: string]: any;
};

// ───────────────── Config & Token helpers ─────────────────

const BASE =
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.DEV ? "http://localhost:8000/api" : "/api");

// Normalise to no trailing slash
const BASE_NORM = BASE.replace(/\/+$/, "");

const TOKEN_KEY = "access_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

export function clearToken() {
  setToken(null);
}

// ───────────────── Internal helpers ─────────────────

function buildUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;

  if (path === "/api") return BASE_NORM;
  if (path.startsWith("/api/")) return `${BASE_NORM}${path.slice(4)}`;

  return `${BASE_NORM}${path.startsWith("/") ? "" : "/"}${path}`;
}

export function apiUrl(path: string): string {
  return buildUrl(path);
}

function shouldSkipAuth(path: string) {
  const p = path.startsWith("http") ? new URL(path).pathname : path;
  return p.startsWith("/auth/login") || p.startsWith("/auth/register");
}

export async function http<T>(
  path: string,
  init?: RequestInit & { parse?: "json" | "text" }
): Promise<T> {
  const url = buildUrl(path);
  const headers = new Headers(
    (init?.headers as Record<string, string> | undefined) ?? undefined
  );

  if (!headers.has("Content-Type") && init?.body) {
    headers.set("Content-Type", "application/json");
  }

  if (!shouldSkipAuth(path)) {
    const tok = getToken();
    if (tok && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${tok}`);
    }
  }

  const res = await fetch(url, { ...init, headers });

  if (!res.ok) {
    let detail: any = null;
    try {
      detail = await res.json();
    } catch {
      try {
        detail = await res.text();
      } catch {
        detail = null;
      }
    }
    const msg =
      (detail && (detail.detail ?? detail.message ?? JSON.stringify(detail))) ||
      `${res.status} ${res.statusText}`;
    throw new Error(msg);
  }

  const parse = init?.parse ?? "json";
  if (parse === "text") return (await res.text()) as unknown as T;
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

// ───────────────── Auth ─────────────────
export async function login(email: string, password: string): Promise<LoginResponse> {
  clearToken();
  const r = await http<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (r?.access_token) setToken(r.access_token);
  return r;
}

export async function register(email: string, password: string): Promise<LoginResponse> {
  clearToken();
  const r = await http<LoginResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (r?.access_token) setToken(r.access_token);
  return r;
}

export async function me(): Promise<User> {
  return http<User>("/auth/me", { method: "GET" });
}

export async function touchAuth(): Promise<{ ok: true }> {
  return http<{ ok: true }>("/auth/touch", { method: "POST" });
}

// ───────────────── Search / TMDb passthrough ─────────────────
export async function searchShows(q: string, arg2: any = 50): Promise<Show[]> {
  const limit = typeof arg2 === "number" ? arg2 : 50;
  const qs = new URLSearchParams({ q, limit: String(limit) }).toString();
  return http<Show[]>(`/tmdb/search?${qs}`, { method: "GET" });
}

export async function getTmdbTvDetails(tmdbId: number): Promise<Show> {
  return http<Show>(`/shows/${tmdbId}`, { method: "GET" });
}

// ───────────────── Library (legacy userId in path) ─────────────────

export async function listFavorites(userId?: number, ..._rest: any[]): Promise<Show[]> {
  const uid = userId ?? (await me()).id;
  return http<Show[]>(`/users/${uid}/favorites`, { method: "GET" });
}

export async function listFavoriteShows(userId?: number): Promise<any[]> {
  const uid = userId ?? (await me()).id;
  return http<any[]>(`/users/${uid}/favorites`, { method: "GET" });
}

export async function addFavorite(
  arg1: number,
  arg2?: number
): Promise<{ ok: true }> {
  const uid = arg2 === undefined ? (await me()).id : arg1;
  const tmdbId = arg2 === undefined ? arg1 : arg2;

  await http(`/users/${uid}/favorites/${tmdbId}`, { method: "POST" });
  return { ok: true };
}

export async function removeFavorite(
  arg1: number,
  arg2?: number
): Promise<{ ok: true }> {
  const uid = arg2 === undefined ? (await me()).id : arg1;
  const tmdbId = arg2 === undefined ? arg1 : arg2;

  await http(`/users/${uid}/favorites/${tmdbId}`, { method: "DELETE" });
  return { ok: true };
}

// Watchlist
export async function listWatchlist(userId: number): Promise<WatchlistItem[]> {
  return http(`/users/${userId}/watchlist`);
}

export async function addWatchlist(
  userId: number,
  tmdbId: number
): Promise<{ ok: true }> {
  await http(`/users/${userId}/watchlist/${tmdbId}`, { method: "POST" });
  return { ok: true };
}

export async function removeWatchlist(
  userId: number,
  tmdbId: number
): Promise<{ ok: true }> {
  await http(`/users/${userId}/watchlist/${tmdbId}`, { method: "DELETE" });
  return { ok: true };
}

// Ratings
export async function listRatings(userId: number, ..._rest: any[]): Promise<UserRating[]> {
  const r = await http<any>(`/ratings/ratings?user_id=${userId}`, { method: "GET" });
  if (Array.isArray(r)) return r as UserRating[];
  if (Array.isArray((r as any)?.ratings)) return (r as any).ratings as UserRating[];
  return [];
}

export async function upsertRating(
  userId: number,
  payload: UserRating,
  ..._rest: any[]
): Promise<UserRating> {
  return http<UserRating>(`/ratings/ratings`, {
    method: "POST",
    body: JSON.stringify({ ...payload, user_id: userId }),
  });
}

// Not interested
export async function listNotInterested(userId?: number): Promise<any[]> {
  const uid = userId ?? (await me()).id;
  return http<any[]>(`/users/${uid}/not-interested`, { method: "GET" });
}

export async function markNotInterested(
  arg1: number,
  arg2?: number
): Promise<{ ok: true }> {
  const uid = arg2 === undefined ? (await me()).id : arg1;
  const tmdbId = arg2 === undefined ? arg1 : arg2;

  await http(`/users/${uid}/not-interested/${tmdbId}`, { method: "POST" });
  return { ok: true };
}

export async function removeNotInterested(
  arg1: number,
  arg2?: number
): Promise<{ ok: true }> {
  const uid = arg2 === undefined ? (await me()).id : arg1;
  const tmdbId = arg2 === undefined ? arg1 : arg2;

  await http(`/users/${uid}/not-interested/${tmdbId}`, { method: "POST" });
  return { ok: true };
}

// Additional legacy aliases some files may import
export const listFavoritesShows = listFavoriteShows;
export const listNotInterestedShows = listNotInterested;

// ───────────────── Discover ─────────────────
export async function getDiscover(
  params?: Record<string, any>
): Promise<DiscoverResponse> {
  const qs = params ? `?${new URLSearchParams(params as any).toString()}` : "";
  return http<DiscoverResponse>(`/discover${qs}`, { method: "GET" });
}

// ───────────────── Recommendations ─────────────────
export async function getRecs(userId: number, opts: RecsOptions = {}): Promise<RecItem[]> {
  const qs = new URLSearchParams(
    { user_id: String(userId), ...((opts as any) ?? {}) } as any
  ).toString();
  return http<RecItem[]>(`/recs?${qs}`, { method: "GET" });
}

export async function getRecsV2(userId: number, opts: RecsOptions = {}): Promise<RecItem[]> {
  const qs = new URLSearchParams(
    { user_id: String(userId), ...((opts as any) ?? {}) } as any
  ).toString();
  return http<RecItem[]>(`/recs/v2?${qs}`, { method: "GET" });
}

export async function getRecsV3(
  arg1: any,
  arg2: any = {},
  ..._rest: any[]
): Promise<RecItem[]> {
  let userId: number;
  let opts: RecsOptions;

  if (typeof arg1 === "number") {
    userId = arg1;
    opts = (arg2 ?? {}) as RecsOptions;
  } else {
    opts = (arg1 ?? {}) as RecsOptions;
    userId = (await me()).id;
  }

  const qs = new URLSearchParams({ ...((opts as any) ?? {}) } as any).toString();

  return http<RecItem[]>(`/recs/v3/${userId}?${qs}`, { method: "GET" });
}

export async function smartSimilar(tmdbId: number, ..._rest: any[]): Promise<RecItem[]> {
  return http<RecItem[]>(`/recs/v3/smart-similar/${tmdbId}`, { method: "GET" });
}

export async function explain(userId: number, tmdbId: number, ..._rest: any[]): Promise<any> {
  return http<any>(`/recs/v3/explain/${userId}/${tmdbId}`, { method: "GET" });
}

// ───────────────── Admin ─────────────────
export async function getAdminStats(): Promise<AdminStats> {
  return http<AdminStats>("/admin/stats", { method: "GET" });
}

export async function adminListUsers(): Promise<AdminUser[]> {
  return http<AdminUser[]>("/admin/users", { method: "GET" });
}

export async function adminDeleteUser(userId: number): Promise<{ ok: true }> {
  await http(`/admin/users/${userId}`, { method: "DELETE" });
  return { ok: true };
}

export async function adminResetPassword(
  userId: number,
  newPassword: string
): Promise<{ ok: true }> {
  await http(`/admin/users/${userId}/reset-password`, {
    method: "POST",
    body: JSON.stringify({ new_password: newPassword }),
  });
  return { ok: true };
}

// ───────────────── Extra legacy aliases ─────────────────
export const getRecsV1 = getRecs;
export const getRecommendations = getRecsV3;
export type { UserRating as Rating };

export type DiscoverResponse = {
  featured: Show[];
  trending: Show[];
  top_decade: Show[];
  drama: Show[];
  crime: Show[];
  thriller: Show[];
};
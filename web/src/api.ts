/* web/src/api.ts — central API helpers & types
 *
 * - Prevents double '/api' prefix via buildUrl()
 * - Favorites & Ratings use: /api/library/{user_id}/...
 * - Includes NOT-INTERESTED, discover, recs v1/v2/v3
 * - Adds admin stats & user-management helpers
 */

// ───────────────── Types ─────────────────
export type User = {
  id: number;
  email: string;
  username?: string | null;
  is_admin: boolean;
};

export type Show = {
  tmdb_id?: number;
  title?: string;
  poster_url?: string | null;
  poster_path?: string | null;
  [k: string]: any;
};

export type UserRating = {
  tmdb_id: number;
  rating: number;
  title?: string | null;
  seasons_completed?: number | null;
  notes?: string | null;
};

export type RecItem = {
  tmdb_id: number;
  title?: string | null;
  score?: number;
  poster_url?: string | null;
  original_language?: string | null;
  genres?: string[];
  [k: string]: any;
};

export type LoginResponse = { access_token: string; token_type?: string };

// ───────────────── Config & Token helpers ─────────────────
const BASE = "/api";
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
  } catch {}
}

export function clearToken() {
  setToken(null);
}

// ───────────────── Internal helpers ─────────────────
function buildUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  if (path === "/api" || path.startsWith("/api/")) return path;
  return `${BASE}${path.startsWith("/") ? "" : "/"}${path}`;
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

  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  if (!shouldSkipAuth(path)) {
    const tok = getToken();
    if (tok && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${tok}`);
    }
  }

  const res = await fetch(url, {
    ...init,
    headers,
    credentials: init?.credentials ?? "same-origin",
  });

  if (res.status === 401) {
    clearToken();
  }

  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (typeof (j as any)?.detail === "string") msg = (j as any).detail;
      else if (Array.isArray((j as any)?.detail) && (j as any).detail[0]?.msg)
        msg = (j as any).detail[0].msg;
    } catch {}
    throw new Error(msg);
  }

  const mode = (init as any)?.parse ?? "json";
  if (mode === "text") return (await res.text()) as unknown as T;
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

// ───────────────── Auth ─────────────────
export async function login(email: string, password: string): Promise<LoginResponse> {
  clearToken();
  return http<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function register(email: string, password: string): Promise<LoginResponse> {
  clearToken();
  return http<LoginResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function me(): Promise<User> {
  return http<User>("/auth/me");
}

// ───────────────── Recs options helper ─────────────────
export type RecsOptions = {
  limit?: number;
  w_tmdb?: number;
  w_reddit?: number;
  w_pair?: number;
  mmr_lambda?: number;
  orig_lang?: string;
  genres?: string[];
  flat?: 0 | 1;
  debug?: 0 | 1;
};

function buildRecsParams(opts: RecsOptions = {}): URLSearchParams {
  const p = new URLSearchParams();
  if (opts.limit != null) p.set("limit", String(opts.limit));
  if (opts.w_tmdb != null) p.set("w_tmdb", String(opts.w_tmdb));
  if (opts.w_reddit != null) p.set("w_reddit", String(opts.w_reddit));
  if (opts.w_pair != null) p.set("w_pair", String(opts.w_pair));
  if (opts.mmr_lambda != null) p.set("mmr_lambda", String(opts.mmr_lambda));
  if (opts.orig_lang) p.set("orig_lang", String(opts.orig_lang));
  if (opts.genres?.length) for (const g of opts.genres) p.append("genres", g);
  p.set("flat", String(opts.flat ?? 1));
  if (opts.debug != null) p.set("debug", String(opts.debug));
  return p;
}

// ───────────────── Search / TMDb ─────────────────
export async function searchShows(q: string, limit = 50): Promise<Show[]> {
  const qs = new URLSearchParams({ q, limit: String(limit) });
  return http<Show[]>(`/tmdb/search?${qs.toString()}`);
}

export async function getTmdbTvDetails(tmdbId: number): Promise<any> {
  return http<any>(`/tmdb/tv/${tmdbId}`);
}

// ───────────────── Favorites ─────────────────
export async function listFavorites(userId: number): Promise<Show[]> {
  return http<Show[]>(`/library/${userId}/favorites`, { method: "GET" });
}

export async function addFavorite(
  userId: number,
  tmdbId: number
): Promise<{ ok: true }> {
  await http(`/library/${userId}/favorites/${tmdbId}`, { method: "POST" });
  return { ok: true };
}

export async function removeFavorite(
  userId: number,
  tmdbId: number
): Promise<{ ok: true }> {
  await http(`/library/${userId}/favorites/${tmdbId}`, { method: "DELETE" });
  return { ok: true };
}

export const listFavoriteShows = listFavorites;

// ───────────────── Ratings ─────────────────
export async function listRatings(userId: number): Promise<UserRating[]> {
  const r = await http<any>(`/library/${userId}/ratings`);
  if (Array.isArray(r)) return r as UserRating[];
  if (Array.isArray((r as any)?.ratings)) return (r as any).ratings as UserRating[];
  return [];
}

export async function upsertRating(
  userId: number,
  payload: UserRating
): Promise<{ ok: boolean }> {
  return http<{ ok: boolean }>(`/library/${userId}/ratings`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ───────────────── Not Interested ─────────────────
export async function listNotInterested(userId: number): Promise<number[]> {
  const r = await http<{ tmdb_id: number }[]>(`/users/${userId}/not-interested`);
  if (!Array.isArray(r)) return [];
  return r.map((row) => Number(row.tmdb_id));
}

export async function markNotInterested(
  userId: number,
  tmdbId: number
): Promise<{ ok: boolean }> {
  await http(`/users/${userId}/not-interested/${tmdbId}`, {
    method: "POST",
  });
  return { ok: true };
}

export async function removeNotInterested(
  userId: number,
  tmdb_id: number
): Promise<{ ok: boolean }> {
  await http(`/users/${userId}/not-interested/${tmdb_id}`, {
    method: "DELETE",
  });
  return { ok: true };
}

// ───────────────── Recs v1/v2/v3 ─────────────────
export async function getRecs(
  userId: number,
  opts: RecsOptions = {}
): Promise<RecItem[] | { items: RecItem[]; meta: any }> {
  const qs = buildRecsParams(opts).toString();
  return http<any>(`/recs/${userId}${qs ? `?${qs}` : ""}`);
}

export async function getRecsV2(
  userId: number,
  opts: RecsOptions = {}
): Promise<RecItem[] | { items: RecItem[]; meta: any }> {
  const qs = buildRecsParams(opts).toString();
  return http<any>(`/recs/v2/${userId}${qs ? `?${qs}` : ""}`);
}

export async function getRecsV3(
  userId: number,
  opts: RecsOptions = {}
): Promise<any> {
  const qs = buildRecsParams(opts).toString();
  return http<any>(`/recs/v3/${userId}${qs ? `?${qs}` : ""}`);
}

// ───────────────── Discover ─────────────────
export interface DiscoverShow {
  tmdb_id: number;
  title: string;
  name?: string;
  overview?: string;
  poster_path?: string;
  first_air_date?: string;
  vote_average?: number;
  vote_count?: number;
  reason?: string;
}

export interface DiscoverPayload {
  featured: DiscoverShow[];
  top_decade: DiscoverShow[];
  trending: DiscoverShow[];
  drama: DiscoverShow[];
  crime: DiscoverShow[];
  documentary: DiscoverShow[];
  scifi_fantasy: DiscoverShow[];
  thriller: DiscoverShow[];
  comedy: DiscoverShow[];
  action_adventure: DiscoverShow[];
  animation: DiscoverShow[];
  family: DiscoverShow[];
}

export async function getDiscover(): Promise<DiscoverPayload> {
  return http<DiscoverPayload>("/discover", { method: "GET" });
}

// ───────────────── Admin (stats & user management) ─────────────────
export interface AdminUser {
  id: number;
  email: string;
  username?: string | null;
  created_at?: string | null;
  is_admin: boolean;
}

export interface AdminStats {
  total_users: number;
  new_users_last_7_days: number;
  total_favorites: number;
  total_ratings: number;
  total_not_interested: number;
  users_with_favorites: number;
  users_with_ratings: number;
}

export async function getAdminStats(): Promise<AdminStats> {
  return http<AdminStats>("/admin/stats");
}

export async function adminListUsers(): Promise<AdminUser[]> {
  return http<AdminUser[]>("/admin/users");
}

export async function adminDeleteUser(userId: number): Promise<void> {
  await http<void>(`/admin/users/${userId}`, { method: "DELETE" });
}

export async function adminResetPassword(
  userId: number,
  newPassword: string
): Promise<void> {
  await http<void>(`/admin/users/${userId}/reset-password`, {
    method: "POST",
    body: JSON.stringify({ new_password: newPassword }),
  });
}

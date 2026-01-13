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
 * - Library (legacy): /api/library/{userId}/favorites|ratings|not_interested
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
};

export type AdminStats = {
  users_total?: number;
  users_active_7d?: number;
  favorites_total?: number;
  ratings_total?: number;
  reddit_posts_total?: number;
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
  // Some older endpoints returned show-like objects; keep it permissive
  title?: string;
  poster_path?: string | null;
  [k: string]: any;
};

export type UserRating = {
  id?: number;
  user_id: number;
  tmdb_id: number;
  rating: number;
  title?: string | null;
  seasons_completed?: number | null;
  notes?: string | null;
  created_at?: string;
  updated_at?: string;
  [k: string]: any;
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

// Prefer env var (set on Vercel): VITE_API_BASE=https://whatnext-api.onrender.com/api
// Fallbacks:
// - development: "/api" (works with local proxy/nginx)
// - production: absolute Render URL (works on Vercel)
const DEFAULT_PROD_API = "https://whatnext-api.onrender.com/api";

const BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  (import.meta.env.MODE === "development" ? "/api" : DEFAULT_PROD_API);

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

// Build full URL for API calls.
// - Absolute URLs pass through.
// - Paths beginning with "/api" are treated as API paths and rewritten to BASE_NORM.
function buildUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;

  // allow callers to pass "/api/..." and still get the right host in prod
  if (path === "/api") return BASE_NORM;
  if (path.startsWith("/api/")) return `${BASE_NORM}${path.slice(4)}`;

  // otherwise treat as relative API path (e.g. "/me", "/auth/login")
  return `${BASE_NORM}${path.startsWith("/") ? "" : "/"}${path}`;
}

// Exported helper for components/pages that still use fetch()
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
    // Try to extract a helpful error message
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
  return http<User>("/me", { method: "GET" });
}

// ───────────────── Search / TMDb passthrough ─────────────────
// Some pages call searchShows(q, token) (old), others call searchShows(q, limit)
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
  return http<Show[]>(`/library/${uid}/favorites`, { method: "GET" });
}

// Allow older code: listFavoriteShows() with no args.
// If userId not provided, we fetch /me first.
export async function listFavoriteShows(userId?: number): Promise<any[]> {
  const uid = userId ?? (await me()).id;
  return http<any[]>(`/library/${uid}/favorites`, { method: "GET" });
}


// Many components call addFavorite(userId, tmdbId, <extra>) — ignore extra args.
export async function addFavorite(
  arg1: number,
  arg2?: number
): Promise<{ ok: true }> {
  const uid = arg2 === undefined ? (await me()).id : arg1;
  const tmdbId = arg2 === undefined ? arg1 : arg2;

  await http(`/library/${uid}/favorites/${tmdbId}`, { method: "POST" });
  return { ok: true };
}



export async function removeFavorite(
  arg1: number,
  arg2?: number
): Promise<{ ok: true }> {
  const uid = arg2 === undefined ? (await me()).id : arg1;
  const tmdbId = arg2 === undefined ? arg1 : arg2;

  await http(`/library/${uid}/favorites/${tmdbId}`, { method: "DELETE" });
  return { ok: true };
}



// Ratings — older pages use listRatings(userId) and sometimes listRatings(userId, token)
export async function listRatings(userId: number, ..._rest: any[]): Promise<UserRating[]> {
  const r = await http<any>(`/library/${userId}/ratings`, { method: "GET" });
  if (Array.isArray(r)) return r as UserRating[];
  if (Array.isArray((r as any)?.ratings)) return (r as any).ratings as UserRating[];
  return [];
}

// Upsert — older pages sometimes pass (userId, payload, token)
export async function upsertRating(
  userId: number,
  payload: UserRating,
  ..._rest: any[]
): Promise<UserRating> {
  return http<UserRating>(`/library/${userId}/ratings`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// Not interested
export async function listNotInterested(userId?: number): Promise<any[]> {
  const uid = userId ?? (await me()).id;
  return http<any[]>(`/library/${uid}/not_interested`, { method: "GET" });
}



export async function markNotInterested(
  arg1: number,
  arg2?: number
): Promise<{ ok: true }> {
  const uid = arg2 === undefined ? (await me()).id : arg1;
  const tmdbId = arg2 === undefined ? arg1 : arg2;

  await http(`/library/${uid}/not_interested/${tmdbId}`, { method: "POST" });
  return { ok: true };
}



export async function removeNotInterested(arg1: number, arg2?: number, ..._rest: any[]): Promise<{ ok: true }> {
  const uid = arg2 === undefined ? (await me()).id : arg1;
  const tmdbId = arg2 === undefined ? arg1 : arg2;

  await http(`/library/${uid}/not_interested/${tmdbId}`, { method: "DELETE" });
  return { ok: true };
}


// Additional legacy aliases some files may import
export const listFavoritesShows = listFavoriteShows; // common typo/variant
export const listNotInterestedShows = listNotInterested;

// ───────────────── Discover ─────────────────
// Some code calls getDiscover() (no args), others call getDiscover(params)
export async function getDiscover(params?: Record<string, any>): Promise<Show[]> {
  const qs = params ? `?${new URLSearchParams(params as any).toString()}` : "";
  return http<Show[]>(`/discover${qs}`, { method: "GET" });
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

// Some pages call getRecsV3(userId, opts), others call getRecsV3(opts) or getRecsV3(userId, opts, token)
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

  const qs = new URLSearchParams(
    { user_id: String(userId), ...((opts as any) ?? {}) } as any
  ).toString();

  return http<RecItem[]>(`/recs/v3?${qs}`, { method: "GET" });
}

// Some components hit these endpoints directly:
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

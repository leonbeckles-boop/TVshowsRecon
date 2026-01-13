/* web/src/api.ts — central API helpers & types
 *
 * - Prevents same-origin "/api" calls on Vercel by supporting an absolute API base.
 * - Uses VITE_API_BASE if set (recommended), otherwise:
 *    - development: "/api"
 *    - production:  "https://whatnext-api.onrender.com/api"
 */

export type AnyDict = Record<string, any>;

export type User = {
  id: number;
  email: string;
  created_at?: string;
  [k: string]: any;
};

export type Genre = {
  id: number;
  name: string;
};

export type Show = {
  show_id: number;
  title: string;
  poster_path?: string | null;
  overview?: string | null;
  first_air_date?: string | null;
  vote_average?: number | null;
  vote_count?: number | null;
  popularity?: number | null;
  original_language?: string | null;
  genre_ids?: number[] | null;
  genres?: Genre[] | null;
  [k: string]: any;
};

export type RedditPost = {
  id: number;
  reddit_id: string;
  subreddit: string;
  title: string;
  url?: string | null;
  created_utc?: string | null;
  score?: number | null;
  num_comments?: number | null;
  [k: string]: any;
};

export type Favorite = {
  id?: number;
  user_id?: number;
  tmdb_id: number;
  created_at?: string;
};

export type Rating = {
  id?: number;
  user_id?: number;
  tmdb_id: number;
  rating: number;
  title?: string;
  seasons_completed?: number | null;
  notes?: string | null;
  created_at?: string;
  updated_at?: string;
  [k: string]: any;
};

export type NotInterested = {
  id?: number;
  user_id?: number;
  tmdb_id: number;
  created_at?: string;
};

export type RedditScore = {
  tmdb_id: number;
  score_reddit: number;
  [k: string]: any;
};

export type RecItem = {
  tmdb_id: number;
  title?: string;
  poster_url?: string | null;
  score?: number;
  reason?: string;
  [k: string]: any;
};

export type ExplainItem = {
  tmdb_id: number;
  title?: string;
  final_score?: number;
  components?: AnyDict;
  neighbors?: AnyDict[];
  [k: string]: any;
};

export type WrappedStats = {
  user_id: number;
  period?: string;
  top_genres?: { name: string; count: number }[];
  top_shows?: { tmdb_id: number; title: string; count: number }[];
  [k: string]: any;
};

export type LoginResponse = { access_token: string; token_type?: string };

// ───────────────── Config & Token helpers ─────────────────

// Prefer env var (set this on Vercel): VITE_API_BASE=https://whatnext-api.onrender.com/api
const BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  (import.meta.env.MODE === "development"
    ? "/api"
    : "https://whatnext-api.onrender.com/api");

// Normalise: no trailing slash
const BASE_NORM = BASE.replace(/\/+$/, "");

const TOKEN_KEY = "access_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // ignore
  }
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

// ───────────────── URL helpers ─────────────────
function buildUrl(path: string): string {
  // Absolute URLs pass through
  if (path.startsWith("http://") || path.startsWith("https://")) return path;

  // Back-compat: callers that already include "/api" shouldn't double-prefix
  let p = path;
  if (p === "/api") p = "";
  else if (p.startsWith("/api/")) p = p.slice(4); // remove leading "/api"

  return `${BASE_NORM}${p.startsWith("/") ? "" : "/"}${p}`;
}

// Exported helper for components/pages
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
  });

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
    const message =
      (detail && (detail.detail ?? detail.message ?? JSON.stringify(detail))) ||
      `${res.status} ${res.statusText}`;
    throw new Error(message);
  }

  const parse = init?.parse ?? "json";
  if (parse === "text") return (await res.text()) as unknown as T;
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
  return http<User>("/me", { method: "GET" });
}

// ───────────────── Discover / Shows ─────────────────
export async function discover(params?: Record<string, any>): Promise<Show[]> {
  const qs = params ? `?${new URLSearchParams(params as any).toString()}` : "";
  return http<Show[]>(`/discover${qs}`, { method: "GET" });
}

export async function showDetails(tmdbId: number): Promise<Show> {
  return http<Show>(`/shows/${tmdbId}`, { method: "GET" });
}

export async function showPosts(tmdbId: number): Promise<RedditPost[]> {
  return http<RedditPost[]>(`/shows/${tmdbId}/posts`, { method: "GET" });
}

// ───────────────── Favorites ─────────────────
export async function favorites(): Promise<Favorite[]> {
  return http<Favorite[]>("/library/favorites", { method: "GET" });
}

export async function addFavorite(tmdbId: number): Promise<Favorite> {
  return http<Favorite>("/library/favorites", {
    method: "POST",
    body: JSON.stringify({ tmdb_id: tmdbId }),
  });
}

export async function removeFavorite(tmdbId: number): Promise<{ ok: boolean }> {
  return http<{ ok: boolean }>(`/library/favorites/${tmdbId}`, {
    method: "DELETE",
  });
}

// ───────────────── Ratings ─────────────────
export async function ratings(): Promise<Rating[]> {
  return http<Rating[]>("/library/ratings", { method: "GET" });
}

export async function upsertRating(payload: Rating): Promise<Rating> {
  return http<Rating>("/library/ratings", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteRating(tmdbId: number): Promise<{ ok: boolean }> {
  return http<{ ok: boolean }>(`/library/ratings/${tmdbId}`, { method: "DELETE" });
}

// ───────────────── Not Interested ─────────────────
export async function notInterested(): Promise<NotInterested[]> {
  return http<NotInterested[]>("/library/not_interested", { method: "GET" });
}

export async function addNotInterested(tmdbId: number): Promise<NotInterested> {
  return http<NotInterested>("/library/not_interested", {
    method: "POST",
    body: JSON.stringify({ tmdb_id: tmdbId }),
  });
}

export async function removeNotInterested(tmdbId: number): Promise<{ ok: boolean }> {
  return http<{ ok: boolean }>(`/library/not_interested/${tmdbId}`, { method: "DELETE" });
}

// ───────────────── Recommendations ─────────────────
export async function recsV3(params?: Record<string, any>): Promise<RecItem[]> {
  const qs = params ? `?${new URLSearchParams(params as any).toString()}` : "";
  return http<RecItem[]>(`/recs/v3${qs}`, { method: "GET" });
}

export async function smartSimilar(tmdbId: number): Promise<RecItem[]> {
  return http<RecItem[]>(`/recs/v3/smart-similar/${tmdbId}`, { method: "GET" });
}

export async function explain(userId: number, tmdbId: number): Promise<ExplainItem> {
  return http<ExplainItem>(`/recs/v3/explain/${userId}/${tmdbId}`, { method: "GET" });
}

// ───────────────── Wrapped ─────────────────
export async function wrapped(userId: number): Promise<WrappedStats> {
  return http<WrappedStats>(`/wrapped/${userId}`, { method: "GET" });
}

// ───────────────── Misc ─────────────────
export async function health(): Promise<{ ok: boolean }> {
  return http<{ ok: boolean }>("/health", { method: "GET" });
}

// NOTE: If you have any components/pages still doing fetch("/api/..."),
// change them to: fetch(apiUrl("/...")) or (better) use the `http()` helpers above.

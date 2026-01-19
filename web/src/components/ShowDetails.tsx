import "./ShowDetails.css";

import React, { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import {
  addFavorite,
  removeFavorite,
  listFavoriteShows,
  listNotInterested,
  markNotInterested,
  removeNotInterested,
  type Show,
  apiUrl,
} from "../api";
import ShowCard from "./ShowCard";

interface TmdbWatchProviderGroup {
  link?: string;
  flatrate?: TmdbWatchProvider[];
  rent?: TmdbWatchProvider[];
  buy?: TmdbWatchProvider[];
  ads?: TmdbWatchProvider[];
  free?: TmdbWatchProvider[];
}

interface TmdbShowDetails extends Show {
  // Extra fields we expect from /api/shows/{id}
  genres?: { id: number; name: string }[];
  number_of_seasons?: number;
  number_of_episodes?: number;
  episode_run_time?: number[];
  status?: string;
  homepage?: string;
  tagline?: string;
  networks?: { id: number; name: string; logo_path?: string | null }[];
  production_companies?: {
    id: number;
    name: string;
    logo_path?: string | null;
    origin_country?: string;
  }[];

  // From TMDb details (if passed through)
  last_air_date?: string;
  first_air_date?: string;
  origin_country?: string[];
  original_language?: string;
  adult?: boolean;
  backdrop_path?: string | null;

  // Where-to-watch fields from backend (if present)
  where_to_watch?: TmdbWatchProviderGroup;
  providers?: TmdbWatchProviderGroup;
}

interface TmdbWatchProvider {
  provider_id: number;
  provider_name: string;
  logo_path?: string | null;
  display_priority?: number;
}

interface RedditPost {
  id: number;
  reddit_id: string;
  subreddit: string;
  title: string;
  url: string;
  created_utc: string;
  score?: number | null;
  num_comments?: number | null;
  permalink?: string | null;
}

type TabKey = "details" | "posts" | "recs" | "explain";

type RecsV3SmartSimilarItem = {
  tmdb_id: number;
  title: string;
  poster_url?: string | null;
  score?: number;
  reason?: string;
  [k: string]: any;
};

type RecsV3ExplainAnchor = {
  tmdb_id: number;
  title?: string;
  final_score?: number;
  components?: Record<string, any>;
  neighbors?: any[];
  [k: string]: any;
};

type RecsV3ExplainResponse = {
  user_id: number;
  anchor_favorites: RecsV3ExplainAnchor[];
  explain_target?: RecsV3ExplainAnchor;
  [k: string]: any;
};

function safeArray<T>(x: any): T[] {
  return Array.isArray(x) ? (x as T[]) : [];
}

function fmtDate(s?: string | null): string {
  if (!s) return "";
  try {
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return s;
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return s;
  }
}

function posterUrl(p?: string | null): string | null {
  if (!p) return null;
  if (p.startsWith("http://") || p.startsWith("https://")) return p;
  return `https://image.tmdb.org/t/p/w500${p}`;
}

function backdropUrl(p?: string | null): string | null {
  if (!p) return null;
  if (p.startsWith("http://") || p.startsWith("https://")) return p;
  return `https://image.tmdb.org/t/p/original${p}`;
}

function providerLogoUrl(p?: string | null): string | null {
  if (!p) return null;
  if (p.startsWith("http://") || p.startsWith("https://")) return p;
  return `https://image.tmdb.org/t/p/w92${p}`;
}

function uniqBy<T>(arr: T[], keyFn: (x: T) => string | number): T[] {
  const seen = new Set<string | number>();
  const out: T[] = [];
  for (const item of arr) {
    const k = keyFn(item);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(item);
  }
  return out;
}

export default function ShowDetails() {
  // ✅ PATCH: support either route param name: /show/:id OR /show/:tmdbId
  const params = useParams<Record<string, string | undefined>>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const idStr = (Object.values(params).find((v) => !!v) ?? "").trim();
  const id = Number(idStr);
  console.log("ShowDetails params:", params, "idStr:", idStr);


  const [tab, setTab] = useState<TabKey>("details");
  const [loading, setLoading] = useState<boolean>(true);
  const [err, setErr] = useState<string | null>(null);

  const [show, setShow] = useState<TmdbShowDetails | null>(null);
  const [posts, setPosts] = useState<RedditPost[]>([]);
  const [recs, setRecs] = useState<RecsV3SmartSimilarItem[]>([]);
  const [explain, setExplain] = useState<RecsV3ExplainResponse | null>(null);

  const [favorites, setFavorites] = useState<number[]>([]);
  const [notInterested, setNotInterested] = useState<number[]>([]);
  const [busyFavorite, setBusyFavorite] = useState(false);
  const [busyNotInterested, setBusyNotInterested] = useState(false);

  const isFavorite = useMemo(() => favorites.includes(id), [favorites, id]);
  const isNotInterested = useMemo(() => notInterested.includes(id), [notInterested, id]);

  const displayPoster = useMemo(() => posterUrl(show?.poster_path ?? null), [show?.poster_path]);
  const displayBackdrop = useMemo(
    () => backdropUrl((show as any)?.backdrop_path ?? null),
    [show]
  );

  const watch = useMemo<TmdbWatchProviderGroup | null>(() => {
    const w = (show?.where_to_watch ?? show?.providers) as any;
    if (!w) return null;
    return w as TmdbWatchProviderGroup;
  }, [show]);

  const watchLists = useMemo(() => {
    const flatrate = safeArray<TmdbWatchProvider>(watch?.flatrate);
    const rent = safeArray<TmdbWatchProvider>(watch?.rent);
    const buy = safeArray<TmdbWatchProvider>(watch?.buy);
    const ads = safeArray<TmdbWatchProvider>(watch?.ads);
    const free = safeArray<TmdbWatchProvider>(watch?.free);

    return {
      flatrate: uniqBy(flatrate, (x) => x.provider_id),
      rent: uniqBy(rent, (x) => x.provider_id),
      buy: uniqBy(buy, (x) => x.provider_id),
      ads: uniqBy(ads, (x) => x.provider_id),
      free: uniqBy(free, (x) => x.provider_id),
    };
  }, [watch]);

  // Load user lists
  useEffect(() => {
    let cancelled = false;

    async function loadUserLists() {
      if (!user) {
        setFavorites([]);
        setNotInterested([]);
        return;
      }
      try {
        const favs = await listFavoriteShows();
        const nis = await listNotInterested();
        if (cancelled) return;
        setFavorites(safeArray<any>(favs).map((x: any) => Number(x.tmdb_id ?? x.show_id ?? x.id)));
        setNotInterested(safeArray<any>(nis).map((x: any) => Number(x.tmdb_id ?? x.show_id ?? x.id)));
      } catch (e: any) {
        // non-fatal
      }
    }

    loadUserLists();
    return () => {
      cancelled = true;
    };
  }, [user]);

  // Load show details + posts + recs (as needed)
  useEffect(() => {
    let cancelled = false;

    async function loadAll() {
      if (!idStr || !id || Number.isNaN(id)) {
        setErr("Invalid show id.");
        setLoading(false);
        return;
      }

      setLoading(true);
      setErr(null);

      try {
        // ✅ PATCH: was fetch(`/api/shows/${id}`)
        const res = await fetch(apiUrl(`/shows/${id}`));
        if (!res.ok) throw new Error(`Failed to load show (${res.status})`);
        const data = (await res.json()) as TmdbShowDetails;
        if (cancelled) return;
        setShow(data);
      } catch (e: any) {
        if (cancelled) return;
        setErr(e?.message ?? "Failed to load show.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadAll();
    return () => {
      cancelled = true;
    };
  }, [id, idStr]);

  // Load posts only when tab is active
  useEffect(() => {
    let cancelled = false;

    async function loadPosts() {
      if (tab !== "posts") return;
      if (!id || Number.isNaN(id)) return;

      try {
        // ✅ PATCH: was fetch(`/api/shows/${id}/posts`)
        const res = await fetch(apiUrl(`/shows/${id}/posts`));
        if (!res.ok) throw new Error(`Failed to load posts (${res.status})`);
        const data = (await res.json()) as RedditPost[];
        if (cancelled) return;
        setPosts(safeArray<RedditPost>(data));
      } catch (e: any) {
        if (cancelled) return;
        setErr(e?.message ?? "Failed to load posts.");
      }
    }

    loadPosts();
    return () => {
      cancelled = true;
    };
  }, [tab, id]);

  // Load recs only when tab is active
  useEffect(() => {
    let cancelled = false;

    async function loadRecs() {
      if (tab !== "recs") return;
      if (!id || Number.isNaN(id)) return;

      try {
        // ✅ PATCH: was fetch(`/api/recs/v3/smart-similar/${id}`)
        const res = await fetch(apiUrl(`/recs/v3/smart-similar/${id}`));
        if (!res.ok) throw new Error(`Failed to load recs (${res.status})`);
        const data = (await res.json()) as RecsV3SmartSimilarItem[];
        if (cancelled) return;
        setRecs(safeArray<RecsV3SmartSimilarItem>(data));
      } catch (e: any) {
        if (cancelled) return;
        setErr(e?.message ?? "Failed to load recs.");
      }
    }

    loadRecs();
    return () => {
      cancelled = true;
    };
  }, [tab, id]);

  // Load explain only when tab is active
  useEffect(() => {
    let cancelled = false;

    async function loadExplain() {
      if (tab !== "explain") return;
      if (!id || Number.isNaN(id)) return;
      if (!user) {
        setExplain(null);
        return;
      }

      try {
        const userId = user.id;
        // ✅ PATCH: was fetch(`/api/recs/v3/explain/${userId}/${id}`)
        const res = await fetch(apiUrl(`/recs/v3/explain/${userId}/${id}`));
        if (!res.ok) throw new Error(`Failed to load explanation (${res.status})`);
        const data = (await res.json()) as RecsV3ExplainResponse;
        if (cancelled) return;
        setExplain(data);
      } catch (e: any) {
        if (cancelled) return;
        setErr(e?.message ?? "Failed to load explanation.");
      }
    }

    loadExplain();
    return () => {
      cancelled = true;
    };
  }, [tab, id, user]);

  async function onToggleFavorite() {
    if (!user) {
      navigate("/login");
      return;
    }
    if (!id || Number.isNaN(id)) return;

    setBusyFavorite(true);
    try {
      if (isFavorite) {
        await removeFavorite(id);
        setFavorites((prev) => prev.filter((x) => x !== id));
      } else {
        await addFavorite(id);
        setFavorites((prev) => [...prev, id]);
      }
    } catch (e: any) {
      setErr(e?.message ?? "Failed to update favorites.");
    } finally {
      setBusyFavorite(false);
    }
  }

  async function onToggleNotInterested() {
    if (!user) {
      navigate("/login");
      return;
    }
    if (!id || Number.isNaN(id)) return;

    setBusyNotInterested(true);
    try {
      if (isNotInterested) {
        await removeNotInterested(id);
        setNotInterested((prev) => prev.filter((x) => x !== id));
      } else {
        await markNotInterested(id);
        setNotInterested((prev) => [...prev, id]);
      }
    } catch (e: any) {
      setErr(e?.message ?? "Failed to update list.");
    } finally {
      setBusyNotInterested(false);
    }
  }

  const title = show?.title ?? "Show Details";

  return (
    <div className="show-details-page">
      <div className="show-details-header">
        <button className="back-btn" onClick={() => navigate(-1)}>
          ← Back
        </button>

        <h1 className="show-details-title">{title}</h1>

        <div className="show-details-actions">
          <button
            className={`fav-btn ${isFavorite ? "is-fav" : ""}`}
            onClick={onToggleFavorite}
            disabled={busyFavorite}
            title={isFavorite ? "Remove from favorites" : "Add to favorites"}
          >
            {isFavorite ? "♥" : "♡"} Favorite
          </button>

          <button
            className={`ni-btn ${isNotInterested ? "is-ni" : ""}`}
            onClick={onToggleNotInterested}
            disabled={busyNotInterested}
            title={isNotInterested ? "Remove from Not Interested" : "Mark Not Interested"}
          >
            {isNotInterested ? "✓" : "＋"} Not Interested
          </button>
        </div>
      </div>

      {err && <div className="error-banner">{err}</div>}

      {loading && <div className="loading">Loading…</div>}

      {!loading && show && (
        <div className="show-details-body">
          <div className="show-hero">
            {displayBackdrop && (
              <div
                className="show-backdrop"
                style={{ backgroundImage: `url(${displayBackdrop})` }}
              />
            )}

            <div className="show-hero-content">
              {displayPoster && (
                <img className="show-poster" src={displayPoster} alt={show.title} />
              )}

              <div className="show-meta">
                {show.tagline && <div className="tagline">“{show.tagline}”</div>}

                <div className="meta-row">
                  {show.first_air_date && <span>{fmtDate(show.first_air_date)}</span>}
                  {show.status && <span>• {show.status}</span>}
                  {typeof show.vote_average === "number" && (
                    <span>• ★ {show.vote_average.toFixed(1)}</span>
                  )}
                </div>

                {show.overview && <p className="overview">{show.overview}</p>}

                {safeArray<any>(show.genres).length > 0 && (
                  <div className="genres">
                    {safeArray<any>(show.genres).map((g: any) => (
                      <span className="genre" key={g.id}>
                        {g.name}
                      </span>
                    ))}
                  </div>
                )}

                {watch && (
                  <div className="watch-section">
                    <h3>Where to watch</h3>

                    {watch.link && (
                      <div className="watch-link">
                        <a href={watch.link} target="_blank" rel="noreferrer">
                          View on TMDb
                        </a>
                      </div>
                    )}

                    {watchLists.flatrate.length > 0 && (
                      <div className="watch-group">
                        <div className="watch-label">Streaming</div>
                        <div className="watch-providers">
                          {watchLists.flatrate.map((p) => (
                            <div className="provider" key={p.provider_id} title={p.provider_name}>
                              {providerLogoUrl(p.logo_path) ? (
                                <img
                                  src={providerLogoUrl(p.logo_path) as string}
                                  alt={p.provider_name}
                                />
                              ) : (
                                <span>{p.provider_name}</span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {watchLists.free.length > 0 && (
                      <div className="watch-group">
                        <div className="watch-label">Free</div>
                        <div className="watch-providers">
                          {watchLists.free.map((p) => (
                            <div className="provider" key={p.provider_id} title={p.provider_name}>
                              {providerLogoUrl(p.logo_path) ? (
                                <img
                                  src={providerLogoUrl(p.logo_path) as string}
                                  alt={p.provider_name}
                                />
                              ) : (
                                <span>{p.provider_name}</span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {watchLists.rent.length > 0 && (
                      <div className="watch-group">
                        <div className="watch-label">Rent</div>
                        <div className="watch-providers">
                          {watchLists.rent.map((p) => (
                            <div className="provider" key={p.provider_id} title={p.provider_name}>
                              {providerLogoUrl(p.logo_path) ? (
                                <img
                                  src={providerLogoUrl(p.logo_path) as string}
                                  alt={p.provider_name}
                                />
                              ) : (
                                <span>{p.provider_name}</span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {watchLists.buy.length > 0 && (
                      <div className="watch-group">
                        <div className="watch-label">Buy</div>
                        <div className="watch-providers">
                          {watchLists.buy.map((p) => (
                            <div className="provider" key={p.provider_id} title={p.provider_name}>
                              {providerLogoUrl(p.logo_path) ? (
                                <img
                                  src={providerLogoUrl(p.logo_path) as string}
                                  alt={p.provider_name}
                                />
                              ) : (
                                <span>{p.provider_name}</span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="show-tabs">
            <button className={tab === "details" ? "active" : ""} onClick={() => setTab("details")}>
              Details
            </button>
            <button className={tab === "posts" ? "active" : ""} onClick={() => setTab("posts")}>
              Reddit posts
            </button>
            <button className={tab === "recs" ? "active" : ""} onClick={() => setTab("recs")}>
              Similar (smart)
            </button>
            <button className={tab === "explain" ? "active" : ""} onClick={() => setTab("explain")}>
              Explain
            </button>
          </div>

          <div className="show-tab-body">
            {tab === "details" && (
              <div className="details-tab">
                <div className="details-grid">
                  <div className="detail">
                    <div className="label">Seasons</div>
                    <div className="value">{show.number_of_seasons ?? "-"}</div>
                  </div>
                  <div className="detail">
                    <div className="label">Episodes</div>
                    <div className="value">{show.number_of_episodes ?? "-"}</div>
                  </div>
                  <div className="detail">
                    <div className="label">Status</div>
                    <div className="value">{show.status ?? "-"}</div>
                  </div>
                  <div className="detail">
                    <div className="label">First aired</div>
                    <div className="value">{fmtDate(show.first_air_date ?? null) || "-"}</div>
                  </div>
                  <div className="detail">
                    <div className="label">Last aired</div>
                    <div className="value">{fmtDate((show as any).last_air_date ?? null) || "-"}</div>
                  </div>
                  <div className="detail">
                    <div className="label">Language</div>
                    <div className="value">{show.original_language ?? "-"}</div>
                  </div>
                </div>

                {safeArray<any>(show.networks).length > 0 && (
                  <div className="networks">
                    <h3>Networks</h3>
                    <div className="network-list">
                      {safeArray<any>(show.networks).map((n: any) => (
                        <div key={n.id} className="network">
                          {n.logo_path ? (
                            <img
                              src={posterUrl(n.logo_path) as string}
                              alt={n.name}
                              title={n.name}
                            />
                          ) : (
                            <span>{n.name}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {safeArray<any>(show.production_companies).length > 0 && (
                  <div className="companies">
                    <h3>Production companies</h3>
                    <div className="company-list">
                      {safeArray<any>(show.production_companies).map((c: any) => (
                        <div key={c.id} className="company">
                          {c.logo_path ? (
                            <img
                              src={posterUrl(c.logo_path) as string}
                              alt={c.name}
                              title={c.name}
                            />
                          ) : (
                            <span>{c.name}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {tab === "posts" && (
              <div className="posts-tab">
                {posts.length === 0 ? (
                  <div className="empty">No Reddit posts found.</div>
                ) : (
                  <ul className="post-list">
                    {posts.map((p) => (
                      <li key={p.id} className="post">
                        <a href={p.url} target="_blank" rel="noreferrer">
                          <div className="post-title">{p.title}</div>
                          <div className="post-meta">
                            r/{p.subreddit} • {fmtDate(p.created_utc)}
                            {typeof p.score === "number" ? ` • ↑ ${p.score}` : ""}
                            {typeof p.num_comments === "number" ? ` • 💬 ${p.num_comments}` : ""}
                          </div>
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {tab === "recs" && (
              <div className="recs-tab">
                {recs.length === 0 ? (
                  <div className="empty">No recommendations found.</div>
                ) : (
                  <div className="recs-grid">
                    {recs.map((r) => (
                      <ShowCard key={r.tmdb_id} show={r as any} />
                    ))}
                  </div>
                )}
              </div>
            )}

            {tab === "explain" && (
              <div className="explain-tab">
                {!user ? (
                  <div className="empty">Log in to see explanation details.</div>
                ) : !explain ? (
                  <div className="empty">No explanation found.</div>
                ) : (
                  <div className="explain-content">
                    <pre className="json">{JSON.stringify(explain, null, 2)}</pre>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {!loading && !show && !err && <div className="empty">Show not found.</div>}
    </div>
  );
}

import "./ShowDetails.css";

import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import {
  addFavorite,
  apiUrl,
  listFavoriteShows,
  listNotInterested,
  markNotInterested,
  removeFavorite,
  removeNotInterested,
  type Show,
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
  genres?: { id: number; name: string }[];
  number_of_seasons?: number;
  number_of_episodes?: number;
  episode_run_time?: number[];
  status?: string;
  homepage?: string;
  tagline?: string;

  first_air_date?: string;
  last_air_date?: string;
  origin_country?: string[];
  original_language?: string;
  backdrop_path?: string | null;

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

type RecsV3SmartSimilarItem = {
  tmdb_id: number;
  title: string;
  poster_url?: string | null;
  score?: number;
  reason?: string;
  [k: string]: any;
};

type TmdbVideoResult = {
  id?: string;
  key?: string;
  site?: string;
  type?: string;
  name?: string;
};

function safeArray<T>(x: unknown): T[] {
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

function pickFirstParam(params: Record<string, string | undefined>): string {
  return (Object.values(params).find((v) => !!v) ?? "").trim();
}

function pickTrailerKey(results: TmdbVideoResult[]): string | null {
  const yt = results.filter((v) => (v.site ?? "").toLowerCase() === "youtube" && !!v.key);

  const officialTrailer = yt.find((v) => (v.type ?? "").toLowerCase().includes("trailer") && (v.name ?? "").toLowerCase().includes("official"));
  if (officialTrailer?.key) return officialTrailer.key;

  const anyTrailer = yt.find((v) => (v.type ?? "").toLowerCase().includes("trailer"));
  if (anyTrailer?.key) return anyTrailer.key;

  return yt[0]?.key ?? null;
}

async function fetchFirstOkJson(urls: string[]): Promise<any | null> {
  for (const u of urls) {
    try {
      const res = await fetch(u);
      if (!res.ok) continue;
      return await res.json();
    } catch {
      // try next
    }
  }
  return null;
}

export default function ShowDetails() {
  // Param-name agnostic: supports /show/:id or /show/:tmdbId (or any single param)
  const params = useParams<Record<string, string | undefined>>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const idStr = pickFirstParam(params);
  const id = Number(idStr);

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const [show, setShow] = useState<TmdbShowDetails | null>(null);

  const [postsLoading, setPostsLoading] = useState(false);
  const [postsErr, setPostsErr] = useState<string | null>(null);
  const [posts, setPosts] = useState<RedditPost[]>([]);

  const [recsLoading, setRecsLoading] = useState(false);
  const [recsErr, setRecsErr] = useState<string | null>(null);
  const [recs, setRecs] = useState<RecsV3SmartSimilarItem[]>([]);

  const [trailerKey, setTrailerKey] = useState<string | null>(null);

  const [watchProviders, setWatchProviders] =
  useState<TmdbWatchProviderGroup | null>(null);


  const [favorites, setFavorites] = useState<number[]>([]);
  const [notInterested, setNotInterested] = useState<number[]>([]);
  const [busyFavorite, setBusyFavorite] = useState(false);
  const [busyNotInterested, setBusyNotInterested] = useState(false);

  const isFavorite = useMemo(() => favorites.includes(id), [favorites, id]);
  const isNotInterested = useMemo(() => notInterested.includes(id), [notInterested, id]);

  const displayPoster = useMemo(() => posterUrl(show?.poster_path ?? null), [show?.poster_path]);

  const genresText = useMemo(() => {
    const gs = safeArray<{ id: number; name: string }>(show?.genres);
    return gs.length ? gs.map((g) => g.name).join(", ") : "";
  }, [show]);

  const watch = watchProviders;


  const watchLists = useMemo(() => {
    const flatrate = uniqBy(safeArray<TmdbWatchProvider>(watch?.flatrate), (x) => x.provider_id);
    const rent = uniqBy(safeArray<TmdbWatchProvider>(watch?.rent), (x) => x.provider_id);
    const buy = uniqBy(safeArray<TmdbWatchProvider>(watch?.buy), (x) => x.provider_id);
    const ads = uniqBy(safeArray<TmdbWatchProvider>(watch?.ads), (x) => x.provider_id);
    const free = uniqBy(safeArray<TmdbWatchProvider>(watch?.free), (x) => x.provider_id);
    return { flatrate, rent, buy, ads, free };
  }, [watch]);

  const trailerEmbed = useMemo(() => {
    if (!trailerKey) return null;
    return `https://www.youtube.com/embed/${trailerKey}`;
  }, [trailerKey]);

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
      } catch {
        // non-fatal
      }
    }

    loadUserLists();
    return () => {
      cancelled = true;
    };
  }, [user]);

  // Load show details
  useEffect(() => {
    let cancelled = false;

    async function loadShow() {
      if (!idStr || Number.isNaN(id) || id <= 0) {
        setErr("Invalid show id.");
        setLoading(false);
        return;
      }

      setLoading(true);
      setErr(null);

      try {
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

    // reset trailer when changing show
    setTrailerKey(null);

    loadShow();
    return () => {
      cancelled = true;
    };
  }, [id, idStr]);

  // Load trailer videos (best-effort, optional)
  useEffect(() => {
    let cancelled = false;

    async function loadTrailer() {
      if (!id || Number.isNaN(id) || id <= 0) return;

      // Try a few common route shapes (depending on how your tmdb router is implemented)
      const payload = await fetchFirstOkJson([
        apiUrl(`/tmdb/tv/${id}/videos`),
        apiUrl(`/tmdb/tv/${id}/videos`),
        apiUrl(`/shows/${id}/videos`),
      ]);

      if (cancelled) return;
      const results = safeArray<TmdbVideoResult>(payload?.results);
      setTrailerKey(pickTrailerKey(results));
    }

    loadTrailer();
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Load watch providers (Where to watch)
useEffect(() => {
  let cancelled = false;

  async function loadWatchProviders() {
    if (!id || Number.isNaN(id) || id <= 0) return;

    try {
      const res = await fetch(apiUrl(`/tmdb/tv/${id}/watch/providers`));
      if (!res.ok) return;

      const data = await res.json();

      // Prefer UK (GB), fallback to US
      const region =
        data?.results?.GB ??
        data?.results?.US ??
        null;

      if (!cancelled) {
        setWatchProviders(region);
      }
    } catch {
      // optional feature – fail silently
    }
  }

  setWatchProviders(null);
  loadWatchProviders();

  return () => {
    cancelled = true;
  };
}, [id]);


  // Load reddit posts (right column)
  useEffect(() => {
    let cancelled = false;

    async function loadPosts() {
      if (!id || Number.isNaN(id)) return;
      setPostsLoading(true);
      setPostsErr(null);

      try {
        const res = await fetch(apiUrl(`/shows/${id}/posts`));
        if (!res.ok) throw new Error(`Failed to load posts (${res.status})`);
        const data = (await res.json()) as RedditPost[];
        if (cancelled) return;
        setPosts(safeArray<RedditPost>(data));
      } catch (e: any) {
        if (cancelled) return;
        setPostsErr(e?.message ?? "Failed to load posts.");
      } finally {
        if (!cancelled) setPostsLoading(false);
      }
    }

    loadPosts();
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Load smart-similar recs (bottom main)
  useEffect(() => {
    let cancelled = false;

    async function loadRecs() {
      if (!id || Number.isNaN(id)) return;
      setRecsLoading(true);
      setRecsErr(null);

      try {
        const res = await fetch(apiUrl(`/recs/v3/smart-similar/${id}`));
        if (!res.ok) throw new Error(`Failed to load recs (${res.status})`);
        const data = (await res.json()) as RecsV3SmartSimilarItem[];
        if (cancelled) return;
        setRecs(safeArray<RecsV3SmartSimilarItem>(data));
      } catch (e: any) {
        if (cancelled) return;
        setRecsErr(e?.message ?? "Failed to load recs.");
      } finally {
        if (!cancelled) setRecsLoading(false);
      }
    }

    loadRecs();
    return () => {
      cancelled = true;
    };
  }, [id]);

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

  // Loading skeleton (matches your CSS)
  if (loading) {
    return (
      <div className="show-details-skeleton">
        <button className="show-details-back" onClick={() => navigate(-1)}>
          ← Back
        </button>
        <div className="show-details-layout">
          <div className="show-details-poster-skel" />
          <div className="show-details-main">
            <div className="show-details-title-skel" />
            <div className="show-details-meta-skel" />
            <div className="show-details-overview-skel" />
            <div className="show-details-buttons-skel" />
          </div>
        </div>
        <div className="show-details-similar-skel">
          <div className="show-details-similar-title-skel" />
          <div className="show-details-similar-grid-skel">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="show-details-similar-card-skel" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (err) {
    return (
      <div className="show-details-page">
        <button className="show-details-back" onClick={() => navigate(-1)}>
          ← Back
        </button>
        <div className="show-details-error">
          <div>Something went wrong.</div>
          <div className="show-details-error-msg">{err}</div>
        </div>
      </div>
    );
  }

  if (!show) {
    return (
      <div className="show-details-page">
        <button className="show-details-back" onClick={() => navigate(-1)}>
          ← Back
        </button>
        <div className="show-details-error">
          <div>Show not found.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="show-details-page">
      <button className="show-details-back" onClick={() => navigate(-1)}>
        ← Back
      </button>

      <div className="show-details-layout">
        <div className="show-details-poster-wrapper">
          {displayPoster ? (
            <img className="show-details-poster" src={displayPoster} alt={show.title} />
          ) : (
            <div className="show-details-poster-placeholder">No poster</div>
          )}
        </div>

        <div className="show-details-main">
          <h1 className="show-details-title">{show.title}</h1>

          <div className="show-details-meta">
            {show.first_air_date && (
              <span className="show-details-meta-item">
                <span className="show-details-meta-sub">First aired</span>
                <span>{fmtDate(show.first_air_date)}</span>
              </span>
            )}
            {show.status && (
              <span className="show-details-meta-item">
                <span className="show-details-meta-sub">Status</span>
                <span>{show.status}</span>
              </span>
            )}
            {typeof show.vote_average === "number" && (
              <span className="show-details-meta-item">
                <span className="show-details-meta-sub">Rating</span>
                <span>★ {show.vote_average.toFixed(1)}</span>
              </span>
            )}
            {genresText && <span className="show-details-meta-genres">{genresText}</span>}
          </div>

          {show.tagline && <div className="show-details-meta-sub">“{show.tagline}”</div>}

          {show.overview && <p className="show-details-overview">{show.overview}</p>}

          <div className="show-details-actions">
            <button
              className={`show-details-fav-btn ${isFavorite ? "is-favorite" : ""}`}
              onClick={onToggleFavorite}
              disabled={busyFavorite}
              title={isFavorite ? "Remove from favorites" : "Add to favorites"}
            >
              <span className="fav-heart">{isFavorite ? "♥" : "♡"}</span>
              <span className="fav-label">Favorite</span>
            </button>

            <button
              className={`show-details-ni-btn ${isNotInterested ? "is-ni" : ""}`}
              onClick={onToggleNotInterested}
              disabled={busyNotInterested}
              title={isNotInterested ? "Remove from Not Interested" : "Mark Not Interested"}
            >
              <span className="ni-icon">{isNotInterested ? "✓" : "＋"}</span>
              <span className="ni-label">Not Interested</span>
            </button>
          </div>

          {watch && (
            <div className="show-details-watch-section">
              <h2>Where to watch</h2>

              {watch.link && (
                <a className="show-details-trailer-btn" href={watch.link} target="_blank" rel="noreferrer">
                  View on TMDb
                </a>
              )}

              <div className="show-details-watch-groups">
                {watchLists.flatrate.length > 0 && (
                  <div className="show-details-watch-group">
                    <h3>Streaming</h3>
                    <div className="show-details-watch-providers">
                      {watchLists.flatrate.map((p) => (
                        <div className="show-details-watch-provider" key={p.provider_id} title={p.provider_name}>
                          {providerLogoUrl(p.logo_path) ? (
                            <img src={providerLogoUrl(p.logo_path) as string} alt={p.provider_name} />
                          ) : (
                            <div className="show-details-watch-provider-placeholder">{p.provider_name}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {watchLists.free.length > 0 && (
                  <div className="show-details-watch-group">
                    <h3>Free</h3>
                    <div className="show-details-watch-providers">
                      {watchLists.free.map((p) => (
                        <div className="show-details-watch-provider" key={p.provider_id} title={p.provider_name}>
                          {providerLogoUrl(p.logo_path) ? (
                            <img src={providerLogoUrl(p.logo_path) as string} alt={p.provider_name} />
                          ) : (
                            <div className="show-details-watch-provider-placeholder">{p.provider_name}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {watchLists.rent.length > 0 && (
                  <div className="show-details-watch-group">
                    <h3>Rent</h3>
                    <div className="show-details-watch-providers">
                      {watchLists.rent.map((p) => (
                        <div className="show-details-watch-provider" key={p.provider_id} title={p.provider_name}>
                          {providerLogoUrl(p.logo_path) ? (
                            <img src={providerLogoUrl(p.logo_path) as string} alt={p.provider_name} />
                          ) : (
                            <div className="show-details-watch-provider-placeholder">{p.provider_name}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {watchLists.buy.length > 0 && (
                  <div className="show-details-watch-group">
                    <h3>Buy</h3>
                    <div className="show-details-watch-providers">
                      {watchLists.buy.map((p) => (
                        <div className="show-details-watch-provider" key={p.provider_id} title={p.provider_name}>
                          {providerLogoUrl(p.logo_path) ? (
                            <img src={providerLogoUrl(p.logo_path) as string} alt={p.provider_name} />
                          ) : (
                            <div className="show-details-watch-provider-placeholder">{p.provider_name}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {trailerEmbed && (
            <div className="show-details-trailer-section">
              <h2>Trailer</h2>
              <div className="show-details-trailer-embed">
                <iframe
                  src={trailerEmbed}
                  title="Trailer"
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                  allowFullScreen
                />
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="show-details-bottom">
        <div className="show-details-bottom-main">
          <div className="show-details-similar-header">
            <h2>Similar shows</h2>
            {recsLoading && <span className="show-details-chip">Loading…</span>}
            {recsErr && <span className="show-details-error-msg-inline">{recsErr}</span>}
          </div>

          {!recsLoading && recs.length === 0 ? (
            <div className="show-details-similar-empty">No recommendations found.</div>
          ) : (
            <div className="show-details-similar-grid">
              {recs.map((r) => (
                <ShowCard key={r.tmdb_id} show={r as any} />
              ))}
            </div>
          )}
        </div>

        <aside className="show-details-reddit">
          <div className="show-details-reddit-header">
            <h2>Reddit</h2>
            {postsLoading && <span className="show-details-chip">Loading…</span>}
          </div>

          {postsErr && <div className="show-details-error-msg-inline">{postsErr}</div>}

          {!postsLoading && posts.length === 0 ? (
            <div className="show-details-reddit-empty">No Reddit posts found.</div>
          ) : (
            <ul className="show-details-reddit-list">
              {posts.slice(0, 12).map((p) => (
                <li key={p.id} className="show-details-reddit-item">
                  <a className="show-details-reddit-title" href={p.url} target="_blank" rel="noreferrer">
                    {p.title}
                  </a>
                  <div className="show-details-reddit-meta">
                    <span>r/{p.subreddit}</span>
                    <span>{fmtDate(p.created_utc)}</span>
                    {typeof p.score === "number" ? <span>↑ {p.score}</span> : null}
                    {typeof p.num_comments === "number" ? <span>💬 {p.num_comments}</span> : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>
    </div>
  );
}

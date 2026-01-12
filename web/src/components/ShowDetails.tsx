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
} from "../api";
import ShowCard from "./ShowCard";

interface TmdbShow {
  id: number;
  tmdb_id?: number; // for consistency with rec API items
  name?: string;
  title?: string;
  poster_path?: string | null;
  poster_url?: string | null;
  overview?: string | null;
  genres?: string[];
  genre_ids?: number[];
  vote_average?: number;
  vote_count?: number;
  popularity?: number;
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
}

interface TmdbWatchProviderGroup {
  flatrate?: TmdbWatchProvider[];
  buy?: TmdbWatchProvider[];
  rent?: TmdbWatchProvider[];
}

interface RedditPost {
  id: number;
  reddit_id: string;
  title: string;
  url: string;
  subreddit: string;
  created_utc: string;
  score: number;
  num_comments: number;
  sentiment: number | null;
  flair_text: string | null;
  flair_css_class: string | null;
}

interface RecsV3ExplainAnchor {
  tmdb_id: number;
  title: string | null;
  poster_path?: string | null;
  poster_url?: string | null;
  similarity?: number | null;
  pair_weight?: number | null;
  shared_genres?: string[] | null;
}

interface RecsV3ExplainPayload {
  tmdb_id: number;
  user_id: number;
  anchor_favorites: RecsV3ExplainAnchor[];
  shared_genres: string[];
  reddit_pairs_strength?: {
    max: number;
    avg: number;
    count: number;
  } | null;
  tmdb_similarity?: {
    max: number;
    avg: number;
    count: number;
  } | null;
  summary_lines: string[];
}

function getTmdbId(show: TmdbShow): number | null {
  if (!show) return null;
  if (typeof show.tmdb_id === "number") return show.tmdb_id;
  if (typeof show.id === "number") return show.id;
  return null;
}

// Basic skeleton for ShowDetails
function DetailsSkeleton() {
  return (
    <div className="show-details-skeleton">
      <div className="show-details-main">
        <div className="show-details-poster-skel" />
        <div className="show-details-info">
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

function useTmdbShow(id: number | null) {
  const [data, setData] = useState<TmdbShow | null>(null);
  const [posts, setPosts] = useState<RedditPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [postsLoading, setPostsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [postsError, setPostsError] = useState<string | null>(null);

  useEffect(() => {
    if (id == null || !Number.isFinite(id) || id <= 0) {
      setData(null);
      setLoading(false);
      setError("Invalid show ID");
      return;
    }

    let cancelled = false;

    const fetchShow = async () => {
      try {
        setLoading(true);
        setError(null);
        const res = await fetch(`/api/shows/${id}`);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const json = (await res.json()) as TmdbShow;
        if (!cancelled) {
          setData(json);
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.message ?? "Failed to load show details");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    fetchShow();

    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (id == null || !Number.isFinite(id) || id <= 0) {
      setPosts([]);
      setPostsLoading(false);
      setPostsError(null);
      return;
    }

    let cancelled = false;

    const fetchPosts = async () => {
      try {
        setPostsLoading(true);
        setPostsError(null);
        const res = await fetch(`/api/shows/${id}/posts`);
        if (!res.ok) {
          if (res.status === 404) {
            // No posts
            if (!cancelled) {
              setPosts([]);
            }
            return;
          }
          throw new Error(`HTTP ${res.status}`);
        }
        const json = (await res.json()) as RedditPost[];
        if (!cancelled) {
          setPosts(json);
        }
      } catch (e: any) {
        if (!cancelled) {
          setPostsError(e?.message ?? "Failed to load Reddit posts");
        }
      } finally {
        if (!cancelled) {
          setPostsLoading(false);
        }
      }
    };

    fetchPosts();

    return () => {
      cancelled = true;
    };
  }, [id]);

  return {
    data,
    posts,
    loading,
    postsLoading,
    error,
    postsError,
  };
}

export function ShowDetails() {
  const params = useParams();
  // Support multiple possible param names: /show/:id, /show/:tmdb_id, /show/:showId
  const rawId =
    (params.id as string | undefined) ??
    (params.tmdb_id as string | undefined) ??
    (params.showId as string | undefined);

  const id = rawId != null ? Number(rawId) : null;

  const navigate = useNavigate();

  const { user } = useAuth();
  const isAuthenticated = !!user;
  const userId = user?.id ?? null;

  const { data, posts, loading, postsLoading, error, postsError } = useTmdbShow(id);

  // crude notification helper instead of ToastProvider
  const notify = (msg: string) => {
    if (typeof window !== "undefined") {
      window.alert(msg);
    } else {
      console.log(msg);
    }
  };

  // Store favourites / not-interested as arrays of tmdb_id
  const [favoriteIds, setFavoriteIds] = useState<number[]>([]);
  const [favoritesLoading, setFavoritesLoading] = useState(false);
  const [favoritesError, setFavoritesError] = useState<string | null>(null);

  const [notInterestedIds, setNotInterestedIds] = useState<number[]>([]);
  const [notInterestedLoading, setNotInterestedLoading] = useState(false);
  const [notInterestedError, setNotInterestedError] = useState<string | null>(null);

  // Smart similar shows state
  const [similar, setSimilar] = useState<any[]>([]);
  const [similarLoading, setSimilarLoading] = useState(false);
  const [similarError, setSimilarError] = useState<string | null>(null);

  // recs_v3 explanation
  const [explain, setExplain] = useState<RecsV3ExplainPayload | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [explainError, setExplainError] = useState<string | null>(null);

  // Fetch favourites and not-interested whenever user changes
  useEffect(() => {
    if (!userId) {
      setFavoriteIds([]);
      setNotInterestedIds([]);
      setFavoritesError(null);
      setNotInterestedError(null);
      return;
    }

    let cancelled = false;

    const fetchFavorites = async () => {
      try {
        setFavoritesLoading(true);
        setFavoritesError(null);
        const favs = await listFavoriteShows(userId); // Show[]
        if (!cancelled) {
          const mapped = (favs || [])
            .map((s: Show) => s.tmdb_id ?? (s as any).id)
            .filter((tid): tid is number => typeof tid === "number");
          setFavoriteIds(mapped);
        }
      } catch (e: any) {
        if (!cancelled) {
          setFavoritesError(e?.message ?? "Failed to load favourites");
        }
      } finally {
        if (!cancelled) {
          setFavoritesLoading(false);
        }
      }
    };

    const fetchNotInterested = async () => {
      try {
        setNotInterestedLoading(true);
        setNotInterestedError(null);
        const ni = await listNotInterested(userId); // number[]
        if (!cancelled) {
          setNotInterestedIds(ni || []);
        }
      } catch (e: any) {
        if (!cancelled) {
          setNotInterestedError(e?.message ?? "Failed to load not-interested list");
        }
      } finally {
        if (!cancelled) {
          setNotInterestedLoading(false);
        }
      }
    };

    fetchFavorites();
    fetchNotInterested();

    return () => {
      cancelled = true;
    };
  }, [userId]);

  // Fetch smart-similar shows
  useEffect(() => {
    if (id == null || !Number.isFinite(id) || id <= 0) {
      setSimilar([]);
      setSimilarError(null);
      return;
    }

    let cancelled = false;

    const fetchSimilar = async () => {
      try {
        setSimilarLoading(true);
        setSimilarError(null);
        const res = await fetch(`/api/recs/v3/smart-similar/${id}`);
        if (!res.ok) {
          if (res.status === 404) {
            if (!cancelled) {
              setSimilar([]);
            }
            return;
          }
          throw new Error(`HTTP ${res.status}`);
        }
        const json = (await res.json()) as any[];
        if (!cancelled) {
          setSimilar(json);
        }
      } catch (e: any) {
        if (!cancelled) {
          setSimilarError(e?.message ?? "Failed to load similar shows");
        }
      } finally {
        if (!cancelled) {
          setSimilarLoading(false);
        }
      }
    };

    fetchSimilar();

    return () => {
      cancelled = true;
    };
  }, [id]);

  // Fetch backend explanation (recs_v3.explain)
  useEffect(() => {
    let cancelled = false;

    if (!userId || id == null || !Number.isFinite(id) || id <= 0) {
      setExplain(null);
      setExplainError(null);
      setExplainLoading(false);
      return;
    }

    const fetchExplain = async () => {
      try {
        setExplainLoading(true);
        setExplainError(null);
        console.log("[ShowDetails] fetching recs_v3 explanation", userId, id);
        const res = await fetch(`/api/recs/v3/explain/${userId}/${id}`);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const json = (await res.json()) as RecsV3ExplainPayload;
        if (!cancelled) {
          setExplain(json);
        }
      } catch (e: any) {
        console.error("[ShowDetails] failed to load recs_v3 explanation", e);
        if (!cancelled) {
          setExplainError(e?.message ?? "Failed to load explanation");
          setExplain(null);
        }
      } finally {
        if (!cancelled) {
          setExplainLoading(false);
        }
      }
    };

    fetchExplain();

    return () => {
      cancelled = true;
    };
  }, [userId, id]);

  const favIdSet = useMemo(() => new Set<number>(favoriteIds), [favoriteIds]);
  const notInterestedSet = useMemo(
    () => new Set<number>(notInterestedIds),
    [notInterestedIds]
  );

  const isFavorite = (show: TmdbShow | null): boolean => {
    if (!show) return false;
    const tid = getTmdbId(show);
    if (!tid) return false;
    return favIdSet.has(tid);
  };

  const isNotInterested = (show: TmdbShow | null): boolean => {
    if (!show) return false;
    const tid = getTmdbId(show);
    if (!tid) return false;
    return notInterestedSet.has(tid);
  };

  const handleToggleFavorite = async () => {
    if (!data) return;
    const tid = getTmdbId(data);
    if (!tid) return;
    if (!userId || !isAuthenticated) {
      notify("Please log in to manage favourites.");
      navigate("/login");
      return;
    }
    try {
      if (favIdSet.has(tid)) {
        await removeFavorite(userId, tid);
        setFavoriteIds((prev) => prev.filter((x) => x !== tid));
        notify("Removed from favourites.");
      } else {
        await addFavorite(userId, tid);
        setFavoriteIds((prev) =>
          prev.includes(tid) ? prev : [...prev, tid]
        );
        notify("Added to favourites.");
      }
    } catch (e: any) {
      notify(e?.message ?? "Failed to update favourites.");
    }
  };

  const handleToggleNotInterested = async () => {
    if (!data) return;
    const tid = getTmdbId(data);
    if (!tid) return;
    if (!userId || !isAuthenticated) {
      notify("Please log in to manage your recommendations.");
      navigate("/login");
      return;
    }
    try {
      if (notInterestedSet.has(tid)) {
        await removeNotInterested(userId, tid);
        setNotInterestedIds((prev) => prev.filter((x) => x !== tid));
        notify("Removed from Not Interested.");
      } else {
        await markNotInterested(userId, tid);
        setNotInterestedIds((prev) =>
          prev.includes(tid) ? prev : [...prev, tid]
        );
        notify("Marked as Not Interested.");
      }
    } catch (e: any) {
      notify(e?.message ?? "Failed to update Not Interested.");
    }
  };

  // Backend-driven explanation with heuristic fallback
  const fallbackSimilarExplanations: string[] = (() => {
    if (!data) return [];
    const lines: string[] = [];

    if (data.genres && data.genres.length > 0) {
      const topGenres = data.genres.slice(0, 3).join(", ");
      lines.push(`Shares similar genres like ${topGenres}.`);
    }

    if (typeof data.vote_average === "number") {
      if (data.vote_average >= 8.5) {
        lines.push("Highly rated by other viewers.");
      } else if (data.vote_average >= 7.5) {
        lines.push("Well rated and liked by most audiences.");
      }
    }

    if (typeof data.popularity === "number" && data.popularity > 20) {
      lines.push("Popular with viewers who enjoy shows like this.");
    }

    if (typeof data.first_air_date === "string" && data.first_air_date.length >= 4) {
      const year = data.first_air_date.slice(0, 4);
      lines.push(`Fits a similar era and style (first aired around ${year}).`);
    }

    return lines;
  })();

  const similarExplanations: string[] =
    explain && Array.isArray(explain.summary_lines) && explain.summary_lines.length > 0
      ? explain.summary_lines
      : fallbackSimilarExplanations;

  const anchorNames: string[] = (() => {
    if (!explain || !Array.isArray(explain.anchor_favorites)) return [];
    const names = explain.anchor_favorites
      .map((a) => a.title)
      .filter((t): t is string => typeof t === "string" && t.trim().length > 0)
      .slice(0, 3);
    return names;
  })();

    const rawProviders: any =
    (data as any)?.where_to_watch ??
    (data as any)?.watch_providers ??
    (data as any)?.providers;

  const providers: TmdbWatchProviderGroup | null = React.useMemo(() => {
    if (!rawProviders) return null;

    const normalize = (
      arr: any[] | undefined
    ): TmdbWatchProvider[] | undefined => {
      if (!Array.isArray(arr) || arr.length === 0) return undefined;

      // Case 1: TMDb-style objects
      if (typeof arr[0] === "object" && arr[0] !== null) {
        return arr.map((p, idx) => ({
          provider_id:
            typeof p.provider_id === "number"
              ? p.provider_id
              : typeof p.id === "number"
              ? p.id
              : idx,
          provider_name:
            typeof p.provider_name === "string"
              ? p.provider_name
              : typeof p.name === "string"
              ? p.name
              : "Unknown",
          logo_path: p.logo_path ?? null,
        }));
      }

      // Case 2: simple string list: ["Netflix", "Disney+", ...]
      if (typeof arr[0] === "string") {
        return arr.map((name: any, idx: number) => ({
          provider_id: idx,
          provider_name: String(name),
          logo_path: null,
        }));
      }

      return undefined;
    };

    return {
      flatrate: normalize(rawProviders.flatrate),
      buy: normalize(rawProviders.buy),
      rent: normalize(rawProviders.rent),
    };
  }, [rawProviders]);


  if (loading) {
    return <DetailsSkeleton />;
  }

  if (error || !data) {
    return (
      <div className="show-details-error">
        <p>Failed to load show details.</p>
        {error && <p className="show-details-error-msg">{error}</p>}
      </div>
    );
  }

  const title = data.title || data.name || "Untitled";
  const posterSrc =
    data.poster_url ||
    (data.poster_path ? `https://image.tmdb.org/t/p/w500${data.poster_path}` : null);
    // Trailer + Cast
    const primaryTrailer = (data as any)?.primary_trailer || null;
    const videos = Array.isArray((data as any)?.videos) ? (data as any).videos : [];
    const cast = Array.isArray((data as any)?.cast) ? (data as any).cast : [];


  const handleBack = () => {
    navigate(-1);
  };

  return (
    <div className="show-details-page">
      <button className="show-details-back" onClick={handleBack}>
        ← Back
      </button>

      <div className="show-details-layout">
        {/* LEFT: Poster */}
        <div className="show-details-poster-wrapper">
          {posterSrc ? (
            <img src={posterSrc} alt={title} className="show-details-poster" />
          ) : (
            <div className="show-details-poster-placeholder">
              <span>No image</span>
            </div>
          )}
        </div>

        {/* RIGHT: Main info */}
        <div className="show-details-main">
          <h1 className="show-details-title">{title}</h1>

          <div className="show-details-meta">
            {data.first_air_date && (
              <span className="show-details-meta-item">
                First aired: {data.first_air_date.slice(0, 10)}
              </span>
            )}
            {typeof data.vote_average === "number" && (
              <span className="show-details-meta-item">
                ⭐ {data.vote_average.toFixed(1)}{" "}
                <span className="show-details-meta-sub">
                  ({data.vote_count ?? 0} ratings)
                </span>
              </span>
            )}
            {data.genres && data.genres.length > 0 && (
              <span className="show-details-meta-item show-details-meta-genres">
                {data.genres.join(" · ")}
              </span>
            )}
          </div>

          <p className="show-details-overview">
            {data.overview || "No overview available."}
          </p>

          <div className="show-details-actions">
            <button
              className={`show-details-fav-btn ${
                isFavorite(data) ? "is-favorite" : "not-favorite"
              }`}
              onClick={handleToggleFavorite}
              disabled={favoritesLoading}
            >
              <span className="fav-heart">{isFavorite(data) ? "♥" : "♡"}</span>
              <span className="fav-label">
                {isFavorite(data) ? "Remove from favourites" : "Add to favourites"}
              </span>
            </button>

            <button
              className={`show-details-ni-btn ${
                isNotInterested(data) ? "is-ni" : "not-ni"
              }`}
              onClick={handleToggleNotInterested}
              disabled={notInterestedLoading}
            >
              <span className="ni-icon">🚫</span>
              <span className="ni-label">
                {isNotInterested(data) ? "Undo Not Interested" : "Not Interested"}
              </span>
            </button>
          </div>

          {(favoritesError || notInterestedError) && (
            <div className="show-details-sub-error">
              {favoritesError && <div>{favoritesError}</div>}
              {notInterestedError && <div>{notInterestedError}</div>}
            </div>
          )}

           {/* Trailer Section */}
            {primaryTrailer && primaryTrailer.site === "YouTube" && (
                <div className="show-details-trailer-section">
                <h2>Trailer</h2>

                <div className="show-details-trailer-embed">
            <iframe
            src={`https://www.youtube.com/embed/${primaryTrailer.key}`}
            title="Trailer"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
         allowFullScreen
         />
        </div>
    </div>
    )}


{/* Optional: show more videos if user wants */}
{!primaryTrailer && videos.length > 0 && (
  <div className="show-details-trailer-section">
    <h2>Videos</h2>
    <div className="show-details-video-thumbs">
      {videos
        .filter((v: any) => v.site === "YouTube")
        .slice(0, 4)
        .map((v: any) => (
          <a
            key={v.id}
            className="show-details-video-thumb"
            href={`https://www.youtube.com/watch?v=${v.key}`}
            target="_blank"
            rel="noreferrer"
             >
            ▶ {v.name}
            </a>
            ))}
        </div>
     </div>
        )}


          {/* Where to watch */}
          {providers && (
            <div className="show-details-watch-section">
              <h2>Where to watch</h2>
              <div className="show-details-watch-groups">
                {providers.flatrate && providers.flatrate.length > 0 && (
                  <div className="show-details-watch-group">
                    <h3>Streaming</h3>
                    <div className="show-details-watch-providers">
                      {providers.flatrate.map((p) => (
                        <div
                          key={`flatrate-${p.provider_id}`}
                          className="show-details-watch-provider"
                        >
                          {p.logo_path ? (
                            <img
                              src={`https://image.tmdb.org/t/p/w92${p.logo_path}`}
                              alt={p.provider_name}
                            />
                          ) : (
                            <div className="show-details-watch-provider-placeholder">
                              {p.provider_name}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {providers.buy && providers.buy.length > 0 && (
                  <div className="show-details-watch-group">
                    <h3>Buy</h3>
                    <div className="show-details-watch-providers">
                      {providers.buy.map((p) => (
                        <div
                          key={`buy-${p.provider_id}`}
                          className="show-details-watch-provider"
                        >
                          {p.logo_path ? (
                            <img
                              src={`https://image.tmdb.org/t/p/w92${p.logo_path}`}
                              alt={p.provider_name}
                            />
                          ) : (
                            <div className="show-details-watch-provider-placeholder">
                              {p.provider_name}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {providers.rent && providers.rent.length > 0 && (
                  <div className="show-details-watch-group">
                    <h3>Rent</h3>
                    <div className="show-details-watch-providers">
                      {providers.rent.map((p) => (
                        <div
                          key={`rent-${p.provider_id}`}
                          className="show-details-watch-provider"
                        >
                          {p.logo_path ? (
                            <img
                              src={`https://image.tmdb.org/t/p/w92${p.logo_path}`}
                              alt={p.provider_name}
                            />
                          ) : (
                            <div className="show-details-watch-provider-placeholder">
                              {p.provider_name}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

          {/* Cast Section */}
{cast.length > 0 && (
  <div className="show-details-cast-section">
    <h2>Cast</h2>
    <div className="show-details-cast-strip">
      {cast.map((actor: any) => (
        <div key={actor.id} className="show-details-cast-card">
          {actor.profile_url ? (
            <img
              src={actor.profile_url}
              alt={actor.name}
              className="show-details-cast-img"
            />
          ) : (
            <div className="show-details-cast-img placeholder">No Image</div>
          )}
          <div className="show-details-cast-name">{actor.name}</div>
          {actor.character && (
            <div className="show-details-cast-role">{actor.character}</div>
          )}
        </div>
      ))}
    </div>
  </div>
)}



      {/* Bottom: smart-similar + explanation + Reddit posts */}
      <div className="show-details-bottom">
        <div className="show-details-bottom-main">
          <div className="show-details-similar-header">
            <h2>Similar shows</h2>
            {similarLoading && <span className="show-details-chip">Loading…</span>}
            {similarError && (
              <span className="show-details-error-msg-inline">
                {similarError}
              </span>
            )}
          </div>

          {similarExplanations.length > 0 && (
            <div className="similar-explain-card">
              <div className="similar-explain-header">
                <span className="similar-explain-icon">⭐</span>
                <span className="similar-explain-title">
                  Because you watched this show…
                </span>
              </div>
              {anchorNames.length > 0 && (
                <div className="similar-explain-anchors">
                  {anchorNames.length === 1 && (
                    <>
                      Anchored on your favourite{" "}
                      <strong>{anchorNames[0]}</strong>.
                    </>
                  )}
                  {anchorNames.length === 2 && (
                    <>
                      Anchored on your favourites{" "}
                      <strong>{anchorNames[0]}</strong> and{" "}
                      <strong>{anchorNames[1]}</strong>.
                    </>
                  )}
                  {anchorNames.length >= 3 && (
                    <>
                      Anchored on your favourites{" "}
                      <strong>{anchorNames[0]}</strong>,{" "}
                      <strong>{anchorNames[1]}</strong> and{" "}
                      <strong>{anchorNames[2]}</strong>.
                    </>
                  )}
                </div>
              )}
              <ul className="similar-explain-list">
                {similarExplanations.map((line, idx) => (
                  <li key={idx}>{line}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="show-details-similar-grid">
            {similarLoading && (
              <>
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="show-details-similar-card-skel" />
                ))}
              </>
            )}
            {!similarLoading && similar.length === 0 && !similarError && (
              <div className="show-details-similar-empty">
                No similar shows found yet.
              </div>
            )}
            {!similarLoading &&
              similar.length > 0 &&
              similar.map((item: any) => {
                const tid: number =
                  typeof item.tmdb_id === "number"
                    ? item.tmdb_id
                    : item.id;
                const isFav = favIdSet.has(tid);
                const isNI = notInterestedSet.has(tid);

                return (
                  <ShowCard
                    key={tid}
                    show={item}
                    isFavorite={isFav}
                    isNotInterested={isNI}
                    onToggleFavorite={async () => {
                      if (!userId || !isAuthenticated) {
                        notify("Please log in to manage favourites.");
                        navigate("/login");
                        return;
                      }
                      try {
                        if (isFav) {
                          await removeFavorite(userId, tid);
                          setFavoriteIds((prev) => prev.filter((x) => x !== tid));
                          notify("Removed from favourites.");
                        } else {
                          await addFavorite(userId, tid);
                          setFavoriteIds((prev) =>
                            prev.includes(tid) ? prev : [...prev, tid]
                          );
                          notify("Added to favourites.");
                        }
                      } catch (e: any) {
                        notify(
                          e?.message ?? "Failed to update favourites from card."
                        );
                      }
                    }}
                    onToggleNotInterested={async () => {
                      if (!userId || !isAuthenticated) {
                        notify("Please log in to manage your recommendations.");
                        navigate("/login");
                        return;
                      }
                      try {
                        if (isNI) {
                          await removeNotInterested(userId, tid);
                          setNotInterestedIds((prev) =>
                            prev.filter((x) => x !== tid)
                          );
                          notify("Removed from Not Interested.");
                        } else {
                          await markNotInterested(userId, tid);
                          setNotInterestedIds((prev) =>
                            prev.includes(tid) ? prev : [...prev, tid]
                          );
                          notify("Marked as Not Interested.");
                        }
                      } catch (e: any) {
                        notify(
                          e?.message ??
                            "Failed to update Not Interested from card."
                        );
                      }
                    }}
                  />
                );
              })}
          </div>
        </div>

        {/* Reddit posts column */}
        <div className="show-details-reddit">
          <div className="show-details-reddit-header">
            <h2>Reddit buzz</h2>
            {postsLoading && (
              <span className="show-details-chip">Loading posts…</span>
            )}
            {postsError && (
              <span className="show-details-error-msg-inline">
                {postsError}
              </span>
            )}
          </div>
          {posts.length === 0 && !postsLoading && !postsError && (
            <div className="show-details-reddit-empty">
              No Reddit posts found for this show yet.
            </div>
          )}
          {posts.length > 0 && (
            <ul className="show-details-reddit-list">
              {posts.map((p) => (
                <li key={p.id} className="show-details-reddit-item">
                  <a
                    href={p.url}
                    target="_blank"
                    rel="noreferrer"
                    className="show-details-reddit-title"
                  >
                    {p.title}
                  </a>
                  <div className="show-details-reddit-meta">
                    <span>/r/{p.subreddit}</span>
                    <span>⬆ {p.score}</span>
                    <span>💬 {p.num_comments}</span>
                  </div>
                  {p.flair_text && (
                    <div className="show-details-reddit-flair">
                      {p.flair_text}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
  
}
export default ShowDetails;

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import ShowCard from "../components/ShowCard";
import PageHeader from "../components/PageHeader";
import {
  getRecsV3,
  getRecsV4,
  listRatings,
  listFavoriteShows,
  addFavorite,
  removeFavorite,
  upsertRating,
  markNotInterested,
  type RecItem,
  type Show,
  type UserRating,
} from "../api";
import "./tileGrid.css";

// Require at least this many favourites before showing any recommendations
const MIN_FAVORITES = 3;

// Shared background with faint grid lines + radial glow at top
const BG_STYLE = {
  minHeight: "100vh",
  width: "100%",
  paddingTop: "162px", // space under fixed PageHeader + big logo
  backgroundColor: "#020617",
  backgroundImage: [
    "radial-gradient(circle at top center, rgba(30,58,138,0.45) 0%, rgba(2,6,23,0.9) 55%, #020617 100%)",
    "linear-gradient(to right, rgba(148,163,184,0.09) 1px, transparent 1px)",
    "linear-gradient(to bottom, rgba(148,163,184,0.09) 1px, transparent 1px)",
  ].join(", "),
  backgroundSize: "auto, 90px 90px, 90px 90px",
  backgroundPosition: "center top, 0 64px, 0 64px",
  backgroundBlendMode: "normal, soft-light, soft-light",
  color: "#e5e7eb",
} as const;

/* --------------------------- helpers --------------------------- */

function getTmdbId(any: any): number | null {
  const cand = any?.tmdb_id ?? any?.external_id ?? any?.id ?? any?.show_id;
  const n = Number(cand);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function getAuthHeaders(): Record<string, string> {
  const h: Record<string, string> = {};
  const token = window.localStorage.getItem("access_token");
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

/* --------------------------- component ------------------------- */

const RecsPage: React.FC = () => {
  const [recEngine, setRecEngine] = useState<"v4" | "v3">("v4");
  const { user } = useAuth();
  const navigate = useNavigate();
  const userId = user?.id ?? null;

  const [items, setItems] = useState<RecItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [favorites, setFavorites] = useState<Show[]>([]);
  const [watchSet, setWatchSet] = useState<Set<number>>(new Set());
  const [favoritesLoaded, setFavoritesLoaded] = useState(false);
  const [hasEnoughFavorites, setHasEnoughFavorites] = useState(false);

  const [ratings, setRatings] = useState<UserRating[]>([]);

  /* --------- redirect when not logged in --------- */

  useEffect(() => {
    if (!userId) {
      navigate("/login", { replace: true, state: { from: "/recs" } });
    }
  }, [userId, navigate]);

  /* --------- derived maps --------- */

  const favSet = useMemo(() => {
    const set = new Set<number>();
    for (const f of favorites) {
      const id = getTmdbId(f);
      if (id) set.add(id);
    }
    return set;
  }, [favorites]);

  const ratingsMap = useMemo(() => {
    const map: Record<number, number> = {};
    for (const r of ratings) {
      const id = (r as any).tmdb_id as number | undefined;
      const val = (r as any).rating as number | undefined;
      if (id && typeof val === "number") {
        map[id] = val;
      }
    }
    return map;
  }, [ratings]);

  /* --------------------------- data loaders --------------------- */

  const loadRecs = useCallback(async () => {
    if (!userId) return;
    if (!hasEnoughFavorites) {
      setItems([]);
      return;
    }

    setLoading(true);
    setErr(null);
    try {
      const data =
        recEngine === "v4"
          ? await getRecsV4(userId, {
              limit: 60,
              flat: 1,
              recent_first: 1,
              recent_years: 3,
            })
          : await getRecsV3(userId, {
              limit: 60,
              flat: 1,
              w_reddit: 0,
              w_semantic: 0.30,
              freshness_boost: 1,
              recent_years: 3,
            });

      const list = Array.isArray(data) ? data : (data as any).items ?? [];

      const cleaned = (list as RecItem[]).filter((item) => {
        const title =
          (item as any).title ??
          (item as any).name ??
          (item as any).original_name ??
          "";
        const hasTitle = typeof title === "string" && title.trim().length > 0;
        const hasPoster = !!(item as any).poster_path || !!(item as any).poster_url;
        return hasTitle || hasPoster;
      });

      setItems(cleaned);
    } catch (e: any) {
      console.error("Failed to load recommendations", e);
      setErr(e?.message ?? "Failed to load recommendations");
    } finally {
      setLoading(false);
    }
  }, [userId, hasEnoughFavorites, recEngine]);

  const loadFavorites = useCallback(async () => {
    if (!userId) return;
    try {
      const favs = await listFavoriteShows(userId);
      const list = favs ?? [];
      setFavorites(list);
      setFavoritesLoaded(true);
      setHasEnoughFavorites(list.length >= MIN_FAVORITES);
    } catch (e) {
      console.error("Failed to load favorites", e);
      setFavoritesLoaded(true);
      setHasEnoughFavorites(false);
    }
  }, [userId]);

  const loadRatings = useCallback(async () => {
    if (!userId) return;
    try {
      const rs = await listRatings(userId);
      setRatings(rs ?? []);
    } catch (e) {
      console.error("Failed to load ratings", e);
    }
  }, [userId]);

  const loadWatchlist = useCallback(async () => {
    if (!userId) return;
    try {
      const res = await fetch(`/api/users/${userId}/watchlist`, {
        headers: getAuthHeaders(),
      });
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();

      const ids = new Set<number>();
      (Array.isArray(data) ? data : []).forEach((x: any) => {
        const id = getTmdbId(x);
        if (id) ids.add(id);
      });
      setWatchSet(ids);
    } catch (e) {
      console.error("Failed to load watchlist", e);
      setWatchSet(new Set());
    }
  }, [userId]);

  /* --------------------------- effects -------------------------- */

  useEffect(() => {
    if (!userId) return;
    loadFavorites();
    loadRatings();
    loadWatchlist();
  }, [userId, loadFavorites, loadRatings, loadWatchlist]);

  useEffect(() => {
    if (!userId) return;
    if (!hasEnoughFavorites) {
      setItems([]);
      return;
    }
    void loadRecs();
  }, [userId, hasEnoughFavorites, loadRecs]);

  /* --------------------------- handlers ------------------------- */

  const handleRefresh = () => {
    if (!userId) return;
    if (!hasEnoughFavorites) return;
    void loadRecs();
  };

  const handleToggleFav = async (show: any) => {
    if (!userId) return;
    const tmdbId = getTmdbId(show);
    if (!tmdbId) return;

    const isCurrentlyFav = favSet.has(tmdbId);
    try {
      if (isCurrentlyFav) {
        await removeFavorite(userId, tmdbId);
        setFavorites((prev) => {
          const next = prev.filter((s) => getTmdbId(s) !== tmdbId);
          setHasEnoughFavorites(next.length >= MIN_FAVORITES);
          return next;
        });
      } else {
        await addFavorite(userId, tmdbId);
        setFavorites((prev) => {
          const next = [...prev, show as Show];
          setHasEnoughFavorites(next.length >= MIN_FAVORITES);
          return next;
        });
      }
    } catch (e) {
      console.error("Failed to toggle favourite", e);
    }
  };

  const handleToggleWatchlist = async (show: any) => {
    if (!userId) return;
    const tmdbId = getTmdbId(show);
    if (!tmdbId) return;

    const isIn = watchSet.has(tmdbId);

    setWatchSet((prev) => {
      const next = new Set(prev);
      isIn ? next.delete(tmdbId) : next.add(tmdbId);
      return next;
    });

    try {
      const res = await fetch(`/api/users/${userId}/watchlist/${tmdbId}`, {
        method: isIn ? "DELETE" : "POST",
        headers: getAuthHeaders(),
      });
      if (!res.ok) throw new Error(String(res.status));
    } catch (e) {
      console.error("Failed to toggle watchlist", e);
      setWatchSet((prev) => {
        const next = new Set(prev);
        isIn ? next.add(tmdbId) : next.delete(tmdbId);
        return next;
      });
    }
  };

  const handleRate = async (show: any, rating: number) => {
    if (!userId) return;
    const tmdbId = getTmdbId(show);
    if (!tmdbId) return;

    try {
      await upsertRating(userId, {
        tmdb_id: tmdbId,
        rating,
        title: (show as any).title ?? (show as any).name ?? "",
      });

      setRatings((prev) => {
        const others = prev.filter((r) => (r as any).tmdb_id !== tmdbId);
        return [
          ...others,
          {
            ...(prev.find((r) => (r as any).tmdb_id === tmdbId) ?? {}),
            tmdb_id: tmdbId,
            rating,
          } as any,
        ];
      });
    } catch (e) {
      console.error("Failed to set rating", e);
    }
  };

  const handleHide = async (show: any) => {
    if (!userId) return;
    const tmdbId = getTmdbId(show);
    if (!tmdbId) return;

    setItems((prev) => prev.filter((s) => getTmdbId(s) !== tmdbId));

    try {
      await markNotInterested(userId, tmdbId);
    } catch (e) {
      console.error("Failed to mark not-interested", e);
    }
  };

  if (!userId) return null;

  const notEnoughFavorites =
    favoritesLoaded && !hasEnoughFavorites && favorites.length < MIN_FAVORITES;

  return (
    <>
      <PageHeader
        title="Personalised TV recommendations"
        subtitle="Generated from your favourites – tuned to your taste profile."
      />

      <div style={BG_STYLE}>
        <main className="mx-auto flex max-w-7xl flex-col gap-6 px-4 pb-10 pt-6">
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr auto auto",
              gap: "14px",
              alignItems: "center",
              border: "1px solid rgba(148, 163, 184, 0.28)",
              background: "rgba(15, 23, 42, 0.72)",
              borderRadius: "18px",
              padding: "12px 16px",
              boxShadow: "0 18px 45px rgba(15, 23, 42, 0.35)",
            }}
          >
            <div style={{ color: "#cbd5e1", fontSize: "14px" }}>
              Use favourites + ratings to improve these recommendations.
            </div>

            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "8px",
                justifySelf: "end",
              }}
            >
              <span
                style={{
                  color: "#94a3b8",
                  fontSize: "14px",
                  letterSpacing: "0.10em",
                  textTransform: "uppercase",
                  marginRight: "2px",
                }}
              >
                Recommedation Engine
              </span>

              <button
                type="button"
                onClick={() => setRecEngine("v4")}
                style={{
                  borderRadius: "999px",
                  border: recEngine === "v4" ? "1px solid rgba(56, 189, 248, 0.75)" : "1px solid rgba(148, 163, 184, 0.35)",
                  background: recEngine === "v4"
                    ? "linear-gradient(to right, rgb(56, 189, 248), rgb(129, 140, 248))"
                    : "rgba(2, 6, 23, 0.45)",
                  color: "#ffffff",
                  padding: "8px 15px",
                  fontSize: "13px",
                  fontWeight: 800,
                  cursor: "pointer",
                  boxShadow: recEngine === "v4" ? "0 15px 35px rgba(8, 47, 73, 0.55)" : "none",
                }}
              >
                Smart
              </button>

              <button
                type="button"
                onClick={() => setRecEngine("v3")}
                style={{
                  borderRadius: "999px",
                  border: recEngine === "v3" ? "1px solid rgba(56, 189, 248, 0.75)" : "1px solid rgba(148, 163, 184, 0.35)",
                  background: recEngine === "v3"
                    ? "linear-gradient(to right, rgb(56, 189, 248), rgb(129, 140, 248))"
                    : "rgba(2, 6, 23, 0.45)",
                  color: "#ffffff",
                  padding: "8px 15px",
                  fontSize: "13px",
                  fontWeight: 800,
                  cursor: "pointer",
                  boxShadow: recEngine === "v3" ? "0 15px 35px rgba(8, 47, 73, 0.55)" : "none",
                }}
              >
                Explore
              </button>
            </div>

            <button
              type="button"
              onClick={handleRefresh}
              style={{
                borderRadius: "999px",
                border: "1px solid rgba(56, 189, 248, 0.55)",
                background: "linear-gradient(to right, rgb(56, 189, 248), rgb(129, 140, 248))",
                color: "#ffffff",
                padding: "8px 16px",
                fontSize: "13px",
                fontWeight: 800,
                cursor: "pointer",
                boxShadow: "0 15px 35px rgba(8, 47, 73, 0.55)",
                justifySelf: "end",
              }}
            >
              Refresh
            </button>
          </div>

          {err && (
            <div className="rounded-2xl border border-red-500/70 bg-red-950/80 px-4 py-3 text-sm text-red-100 shadow-lg shadow-red-950/70">
              {err}
            </div>
          )}

          {loading ? (
            <section
              style={{
                border: "1px solid rgba(148, 163, 184, 0.22)",
                background: "rgba(15, 23, 42, 0.68)",
                borderRadius: "22px",
                padding: "18px",
                boxShadow: "0 22px 55px rgba(2, 6, 23, 0.5)",
              }}
            >
              <div className="mb-4 flex items-center justify-between gap-4">
                <div>
                  <div className="text-base font-semibold text-slate-100">
                    Finding better matches…
                  </div>
                  <div className="mt-1 text-xs text-slate-400">
                    Matching your favourites against tone, quality and audience signals.
                  </div>
                </div>
                <div
                  style={{
                    borderRadius: "999px",
                    border: "1px solid rgba(56, 189, 248, 0.45)",
                    padding: "6px 12px",
                    color: "#bae6fd",
                    fontSize: "12px",
                    background: "rgba(8, 47, 73, 0.35)",
                  }}
                >
                  {recEngine === "v4" ? "Smart v4" : "Explore v3"}
                </div>
              </div>

              <div className="tile-grid">
                {Array.from({ length: 12 }).map((_, i) => (
                  <div
                    key={i}
                    style={{
                      minHeight: "330px",
                      borderRadius: "18px",
                      border: "1px solid rgba(148, 163, 184, 0.18)",
                      background:
                        "linear-gradient(135deg, rgba(30, 41, 59, 0.95), rgba(15, 23, 42, 0.72))",
                      overflow: "hidden",
                      position: "relative",
                    }}
                  >
                    <div
                      style={{
                        height: "78%",
                        background:
                          "linear-gradient(110deg, rgba(51, 65, 85, 0.55), rgba(100, 116, 139, 0.18), rgba(51, 65, 85, 0.55))",
                      }}
                    />
                    <div style={{ padding: "12px" }}>
                      <div
                        style={{
                          height: "12px",
                          width: "68%",
                          borderRadius: "999px",
                          background: "rgba(148, 163, 184, 0.28)",
                          marginBottom: "8px",
                        }}
                      />
                      <div
                        style={{
                          height: "9px",
                          width: "42%",
                          borderRadius: "999px",
                          background: "rgba(148, 163, 184, 0.18)",
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ) : notEnoughFavorites ? (
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 px-4 py-4 text-sm text-slate-300 shadow-lg shadow-slate-950/70">
              <div className="text-slate-100 text-base md:text-lg mb-1">
                Add a few favourites to get started
              </div>
              <div className="text-xs md:text-sm text-slate-400">
                Your personalised recommendations will appear here once you’ve
                added at least{" "}
                <span className="font-semibold">{MIN_FAVORITES}</span> favourite
                shows. Head to <span className="font-semibold">Discover</span>{" "}
                and tap the heart icon on series you love.
              </div>
            </div>
          ) : items.length === 0 ? (
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 px-4 py-4 text-sm text-slate-300 shadow-lg shadow-slate-950/70">
              No recommendations yet. Try adding a couple more favourites.
            </div>
          ) : (
            <section className="space-y-3">
              <div className="flex items-baseline justify-between gap-2">
                <h2 className="text-sm font-semibold text-slate-100">
                  Recommended for you
                </h2>
                <p className="text-[11px] text-slate-400">
                  {recEngine === "v4"
                    ? "Smart v4: tighter recommendations based on tone, fit and quality."
                    : "Explore v3: broader recommendations for a different perspective."}
                </p>
              </div>

              <div className="tile-grid">
                {items.map((s) => {
                  const tmdbId = getTmdbId(s) ?? undefined;
                  const key = String(tmdbId ?? (s as any).show_id ?? Math.random());
                  const isFav = tmdbId ? favSet.has(tmdbId) : false;
                  const isWatchlist = tmdbId ? watchSet.has(tmdbId) : false;

                  return (
                    <ShowCard
                      key={key}
                      show={s as any}
                      myRating={tmdbId ? ratingsMap[tmdbId] : undefined}
                      isFav={isFav}
                      onToggleFav={() => handleToggleFav(s)}
                      isWatchlist={isWatchlist}
                      onToggleWatchlist={() => handleToggleWatchlist(s)}
                      onRate={(r) => handleRate(s, r)}
                      onHide={() => handleHide(s)}
                      variant="glass"
                      reasons={(s as any).reasons ?? undefined}
                    />
                  );
                })}
              </div>
            </section>
          )}

          <footer className="pt-4 text-[10px] text-slate-500">
            build: {import.meta.env.MODE} {import.meta.env.VITE_BUILD_ID ?? ""}
          </footer>
        </main>
      </div>
    </>
  );
};

export default RecsPage;

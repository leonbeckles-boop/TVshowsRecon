import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import ShowCard from "../components/ShowCard";
import PageHeader from "../components/PageHeader";
import GenreChips from "../components/GenreChips";
import {
  getRecsV3,
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
  paddingTop: "128px", // space under fixed PageHeader + big logo
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

function parseGenresFromURL(): string[] {
  if (typeof window === "undefined") return [];
  const params = new URLSearchParams(window.location.search);
  const raw = params.get("genres");
  if (!raw) return [];
  return raw
    .split(",")
    .map((g) => g.trim())
    .filter(Boolean);
}

function writeGenresToURL(genres: string[]) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (genres.length === 0) {
    url.searchParams.delete("genres");
  } else {
    url.searchParams.set("genres", genres.join(","));
  }
  window.history.replaceState(null, "", url.toString());
}

/* --------------------------- component ------------------------- */

const RecsPage: React.FC = () => {
  const [tileVariant, setTileVariant] = useState<"poster" | "glass">("poster");
  const { user } = useAuth();
  const navigate = useNavigate();
  const userId = user?.id ?? null;

  const [items, setItems] = useState<RecItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [favorites, setFavorites] = useState<Show[]>([]);
  const [favoritesLoaded, setFavoritesLoaded] = useState(false);
  const [hasEnoughFavorites, setHasEnoughFavorites] = useState(false);

  const [ratings, setRatings] = useState<UserRating[]>([]);
  const [selectedGenres, setSelectedGenres] = useState<string[]>(
    () => parseGenresFromURL(),
  );

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
      // Defensive: ensure we don't fetch recs for users with too few favourites
      setItems([]);
      return;
    }

    setLoading(true);
    setErr(null);
    try {
      const data = await getRecsV3(userId, {
        limit: 60,
        flat: 1,
        genres: selectedGenres.length ? selectedGenres : undefined,
      });

      const list = Array.isArray(data) ? data : (data as any).items ?? [];

      // Filter out “ghost” items with no title AND no poster
      const cleaned = (list as RecItem[]).filter((item) => {
        const title =
          (item as any).title ??
          (item as any).name ??
          (item as any).original_name ??
          "";
        const hasTitle = typeof title === "string" && title.trim().length > 0;
        const hasPoster =
          !!(item as any).poster_path || !!(item as any).poster_url;
        return hasTitle || hasPoster;
      });

      setItems(cleaned);
    } catch (e: any) {
      console.error("Failed to load recommendations", e);
      setErr(e?.message ?? "Failed to load recommendations");
    } finally {
      setLoading(false);
    }
  }, [userId, selectedGenres, hasEnoughFavorites]);

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

  /* --------------------------- effects -------------------------- */

  useEffect(() => {
    if (!userId) return;
    loadFavorites();
    loadRatings();
  }, [userId, loadFavorites, loadRatings]);

  // Trigger recs loading only when we have enough favourites
  useEffect(() => {
    if (!userId) return;
    if (!hasEnoughFavorites) {
      // Not enough favourites: ensure we clear any previous recs
      setItems([]);
      return;
    }
    void loadRecs();
  }, [userId, hasEnoughFavorites, loadRecs]);

  /* --------------------------- handlers ------------------------- */

  const handleGenresChange = (genres: string[]) => {
    setSelectedGenres(genres);
    writeGenresToURL(genres);
  };

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

  /* --------------------------- render states -------------------- */

  // While redirecting, render nothing to avoid flicker
  if (!userId) {
    return null;
  }

  const notEnoughFavorites =
    favoritesLoaded && !hasEnoughFavorites && favorites.length < MIN_FAVORITES;

  /* --------------------------- main render ---------------------- */

  return (
    <>
      <PageHeader
        title="Personalised TV recommendations"
        subtitle="Generated from your favourites – tuned to your taste profile."
      />

      {/* Tile style toggle for testers */}
      <div className="max-w-screen-2xl mx-auto px-4 md:px-8 mt-3 flex justify-end">
        <div className="inline-flex items-center gap-2 rounded-full border border-slate-600/70 bg-slate-900/70 px-3 py-1 text-xs text-slate-200">
          <span className="uppercase tracking-[0.18em] text-[10px] text-slate-400">
            Tile style
          </span>
          <button
            type="button"
            onClick={() => setTileVariant("poster")}
            className={
              "px-2 py-0.5 rounded-full border text-[11px] " +
              (tileVariant === "poster"
                ? "bg-slate-100 text-slate-900 border-slate-200"
                : "border-slate-600 text-slate-200")
            }
          >
            Poster only
          </button>
          <button
            type="button"
            onClick={() => setTileVariant("glass")}
            className={
              "px-2 py-0.5 rounded-full border text-[11px] " +
              (tileVariant === "glass"
                ? "bg-slate-100 text-slate-900 border-slate-200"
                : "border-slate-600 text-slate-200")
            }
          >
            Poster + title
          </button>
        </div>
      </div>

      <div style={BG_STYLE}>
        <main className="mx-auto flex max-w-7xl flex-col gap-6 px-4 pb-10 pt-6">
          {/* Optional refresh button row */}
          <div className="flex items-center justify-between gap-4">
            <div className="text-sm text-slate-300">
              Use favourites + ratings to improve these recommendations.
            </div>
            <button
              type="button"
              onClick={handleRefresh}
              className="inline-flex items-center justify-center rounded-full px-5 py-2.5 text-sm font-medium text-white"
              style={{
                background:
                  "linear-gradient(to right, rgb(56, 189, 248), rgb(129, 140, 248))",
                boxShadow: "0 15px 35px rgba(8, 47, 73, 0.9)",
              }}
            >
              Refresh
            </button>
          </div>

          {/* Genres */}
          <section className="flex items-center gap-4 min-w-[380px] justify-end">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-3">Filter by genre</h2>
              {selectedGenres.length > 0 && (
                <button
                  type="button"
                  onClick={() => handleGenresChange([])}
                  className="inline-flex items-center justify-center
                    rounded-full
                    text-[18px] md:text-[20px] font-semibold
                    no-underline select-none
                    transition-all duration-200"
                >
                  Clear ({selectedGenres.length})
                </button>
              )}
            </div>
            <GenreChips
              initialSelected={selectedGenres}
              onChange={handleGenresChange}
            />
          </section>

          {/* Status / helper states */}
          {err && (
            <div className="rounded-2xl border border-red-500/70 bg-red-950/80 px-4 py-3 text-sm text-red-100 shadow-lg shadow-red-950/70">
              {err}
            </div>
          )}

          {loading ? (
            <div className="rounded-2xl border border-slate-800 bg-slate-950/80 px-4 py-6 text-sm text-slate-300 shadow-lg shadow-slate-950/70">
              <div className="mb-1 text-slate-100">
                Loading recommendations…
              </div>
              <div className="text-xs text-slate-400">
                We&apos;re matching your favourites with fresh shows you&apos;re
                likely to enjoy.
              </div>
            </div>
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
              No recommendations yet. Try adjusting your genre filters or adding
              a couple more favourites.
            </div>
          ) : (
            <section className="space-y-3">
              <div className="flex items-baseline justify-between gap-2">
                <h2 className="text-sm font-semibold text-slate-100">
                  Recommended for you
                </h2>
                <p className="text-[11px] text-slate-400">
                  Based on your favourites, quality and taste profile.
                </p>
              </div>

              {/* Responsive grid – same sizing as Search/Favourites */}
              <div className="tile-grid">
                {items.map((s) => {
                  const tmdbId = getTmdbId(s) ?? undefined;
                  const key = String(
                    tmdbId ?? (s as any).show_id ?? Math.random(),
                  );
                  const isFav = tmdbId ? favSet.has(tmdbId) : false;

                  return (
                    <ShowCard
                      key={key}
                      show={s as any}
                      myRating={tmdbId ? ratingsMap[tmdbId] : undefined}
                      isFav={isFav}
                      onToggleFav={() => handleToggleFav(s)}
                      onRate={(r) => handleRate(s, r)}
                      onHide={() => handleHide(s)}
                      variant={tileVariant}
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

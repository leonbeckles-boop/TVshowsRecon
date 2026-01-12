import { useEffect, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";

import {
  searchShows,
  listFavorites,
  listRatings,
  addFavorite,
  removeFavorite,
  upsertRating,
  markNotInterested,
  type Show,
} from "../api";
import { useAuth } from "../auth/AuthProvider";
import ShowCard from "../components/ShowCard";

// Shared background with faint grid lines + radial glow at top
const BG_STYLE = {
  minHeight: "100vh",
  width: "100%",
  paddingTop: "156px", // space under fixed PageHeader + big logo
  backgroundColor: "#020617",
  backgroundImage: [
    // stronger top glow to tie into header
    "radial-gradient(circle at top center, rgba(30,58,138,0.45) 0%, rgba(2,6,23,0.9) 55%, #020617 100%)",
    // faint gridlines
    "linear-gradient(to right, rgba(148,163,184,0.09) 1px, transparent 1px)",
    "linear-gradient(to bottom, rgba(148,163,184,0.09) 1px, transparent 1px)",
  ].join(", "),
  backgroundSize: "auto, 90px 90px, 90px 90px",
  backgroundPosition: "center top, 0 64px, 0 64px",
  backgroundBlendMode: "normal, soft-light, soft-light",
  color: "#e5e7eb",
} as const;

function tmdbFromShow(s: Show): number | null {
  const v = Number((s as any).tmdb_id ?? (s as any).external_id ?? (s as any).show_id);
  return Number.isFinite(v) && v > 0 ? v : null;
}

export default function SearchPage() {
  const { user } = useAuth();
  const userId = user?.id ?? 0;

  const [query, setQuery] = useState("Breaking Bad"); // preload
  const [results, setResults] = useState<Show[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // favourites + my ratings
  const [favSet, setFavSet] = useState<Set<number>>(new Set());
  const [ratingsMap, setRatingsMap] = useState<Record<number, number>>({});

  // load favourites + ratings when user changes
  useEffect(() => {
    let alive = true;
    async function run() {
      if (!userId) {
        setFavSet(new Set());
        setRatingsMap({});
        return;
      }
      try {
        const [favs, ratings] = await Promise.all([
          listFavorites(userId),
          listRatings(userId),
        ]);
        if (!alive) return;

        const favIds = new Set<number>();
        (favs ?? []).forEach((s: any) => {
          const t =
            typeof s === "number"
              ? s
              : Number(s.tmdb_id ?? s.external_id ?? s.show_id);
          if (Number.isFinite(t) && t > 0) favIds.add(t);
        });
        setFavSet(favIds);

        const rmap: Record<number, number> = {};
        (ratings ?? []).forEach((r: any) => {
          if (typeof r.tmdb_id === "number" && typeof r.rating === "number") {
            rmap[r.tmdb_id] = r.rating;
          }
        });
        setRatingsMap(rmap);
      } catch {
        if (!alive) return;
        setFavSet(new Set());
        setRatingsMap({});
      }
    }
    void run();
    return () => {
      alive = false;
    };
  }, [userId]);

  // run search whenever query changes
  useEffect(() => {
    let alive = true;
    async function run() {
      setLoading(true);
      setErr(null);
      try {
        const data = await searchShows(query);
        if (!alive) return;
        setResults(data ?? []);
      } catch (e: any) {
        if (!alive) return;
        setErr(e?.message || "Failed to search shows");
        setResults([]);
      } finally {
        if (alive) setLoading(false);
      }
    }
    if (query && query.trim().length > 0) {
      void run();
    } else {
      setResults([]);
    }
    return () => {
      alive = false;
    };
  }, [query]);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    // search already runs via effect on query change
  }

  async function toggleFav(show: Show) {
    if (!userId) {
      alert("Please log in to use favourites.");
      return;
    }
    const tmdb = tmdbFromShow(show);
    if (!tmdb) return;

    const isFav = favSet.has(tmdb);
    // optimistic UI
    setFavSet((prev) => {
      const next = new Set(prev);
      isFav ? next.delete(tmdb) : next.add(tmdb);
      return next;
    });

    try {
      if (isFav) await removeFavorite(userId, tmdb);
      else await addFavorite(userId, tmdb);
    } catch (e: any) {
      // revert on failure
      setFavSet((prev) => {
        const next = new Set(prev);
        isFav ? next.add(tmdb) : next.delete(tmdb);
        return next;
      });
      alert(e?.message || "Failed to update favourite");
    }
  }

  async function rate(show: Show, rating: number) {
    if (!userId) {
      alert("Please log in to rate shows.");
      return;
    }
    const tmdb = tmdbFromShow(show);
    if (!tmdb) return;

    try {
      await upsertRating(userId, {
        tmdb_id: tmdb,
        rating,
        title: (show as any).title,
      });
      setRatingsMap((m) => ({ ...m, [tmdb]: rating }));
    } catch (e: any) {
      alert(e?.message || "Failed to save rating");
    }
  }

  async function hide(show: Show) {
    const tmdb = tmdbFromShow(show);
    try {
      if (userId && tmdb) await markNotInterested(userId, tmdb);
    } finally {
      setResults((prev) => prev.filter((s: any) => s.show_id !== (show as any).show_id));
    }
  }

  // Centered, chunky search bar
  const form = useMemo(
    () => (
      <form
        onSubmit={onSubmit}
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: "2.5rem",
          marginTop: "1.5rem",
          width: "100%",
        }}
      >
        <input
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
          placeholder="Search for a TV show…"
          style={{
            width: "100%",
            maxWidth: "720px",
            borderRadius: "9999px",
            border: "1px solid rgba(56, 189, 248, 0.4)",
            backgroundColor: "rgba(15, 23, 42, 0.9)",
            padding: "1rem 1.5rem",
            fontSize: "1.25rem",
            color: "#e5e7eb",
            boxShadow: "0 0 30px rgba(56, 189, 248, 0.15)",
            outline: "none",
          }}
        />
        <button
          type="submit"
          disabled={loading}
          title="Search"
          style={{
            marginTop: "1rem",
            borderRadius: "9999px",
            padding: "0.8rem 2.8rem",
            fontSize: "1.1rem",
            fontWeight: 600,
            color: "#ffffff",
            backgroundColor: "rgba(15, 23, 42, 0.9)",
            border: "2px solid rgb(251,191,36)", // amber-400
            boxShadow: "0 0 10px rgba(251,191,36,0.8)",
            cursor: loading ? "default" : "pointer",
            opacity: loading ? 0.7 : 1,
          }}
        >
          🔍 {loading ? "Searching…" : "Search"}
        </button>
      </form>
    ),
    [query, loading],
  );

  return (
    <>
      <PageHeader
        title="Search the TV universe"
        subtitle="Look up any show, then add it to your favourites or rate it to train your recommendations."
        
      />

      <div style={BG_STYLE}>
        <main className="mx-auto max-w-6xl px-4 pb-10 pt-6">
          {form}

          {err && (
            <div className="mb-3 rounded border border-red-500/70 bg-red-950/80 px-3 py-2 text-sm text-red-100">
              {err}
            </div>
          )}

          {!results.length && !loading ? (
            <div className="text-sm text-slate-400">No results.</div>
          ) : (
            <>
              {loading && (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns:
                      "repeat(auto-fill, minmax(270px, 1fr))",
                    gap: "24px",
                    alignItems: "flex-start",
                  }}
                >
                  {Array.from({ length: 12 }).map((_, i) => (
                    <div
                      key={i}
                      className="aspect-[2/3] animate-pulse rounded-2xl bg-slate-800/80"
                    />
                  ))}
                </div>
              )}

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns:
                    "repeat(auto-fill, minmax(270px, 1fr))",
                  gap: "24px",
                  alignItems: "flex-start",
                }}
              >
                {results.map((show) => {
                  const tmdb = tmdbFromShow(show) ?? undefined;
                  const isFav = tmdb ? favSet.has(tmdb) : false;
                  const myRating = tmdb ? ratingsMap[tmdb] : undefined;

                  return (
                    <ShowCard
                      key={`${(show as any).show_id}-${(show as any).title}`}
                      show={show}
                      myRating={myRating}
                      isFav={isFav}
                      onToggleFav={() => toggleFav(show)}
                      onRate={(r) => rate(show, r)}
                      onHide={() => hide(show)}
                      reasons={(show as any).reasons ?? (show as any).debug_reasons}
                    />
                  );
                })}
              </div>
            </>
          )}
        </main>
      </div>
    </>
  );
}

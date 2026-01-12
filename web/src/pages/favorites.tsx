import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import PageHeader from "../components/PageHeader";
import ShowCard from "../components/ShowCard";
import "./tileGrid.css";

import {
  listFavoriteShows,
  listRatings,
  removeFavorite,
  type Show,
  type UserRating,
  upsertRating,
} from "../api";
import { useAuth } from "../auth/AuthProvider";

const TMDB_IMG = "https://image.tmdb.org/t/p/w500";

function getTmdbId(any: any): number | null {
  const cand = any?.tmdb_id ?? any?.external_id ?? any?.id ?? any?.show_id;
  const n = Number(cand);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function posterUrl(show: any): string | undefined {
  const direct = show?.poster_url ?? show?.posterUrl;
  if (direct && typeof direct === "string") return direct;

  const path =
    show?.poster_path ?? show?.posterPath ?? show?.image ?? show?.backdrop_path;
  if (path && typeof path === "string") return `${TMDB_IMG}${path}`;

  return undefined;
}

export default function FavoritesPage() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [list, setList] = useState<Show[]>([]);
  const [ratings, setRatings] = useState<UserRating[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [loadingRatings, setLoadingRatings] = useState<boolean>(false);
  const [tileVariant, setTileVariant] = useState<"poster" | "glass">("poster");

  const ratingsMap = useMemo(() => {
    const map: Record<number, UserRating> = {};
    for (const r of ratings) {
      const tmdb = getTmdbId(r);
      if (tmdb != null) {
        map[tmdb] = r;
      }
    }
    return map;
  }, [ratings]);

  const fetchFavorites = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const favs = await listFavoriteShows(user.id);
      setList(favs ?? []);
    } catch (err) {
      console.error("Failed to fetch favourites:", err);
    } finally {
      setLoading(false);
    }
  }, [user]);

  const fetchRatings = useCallback(async () => {
    if (!user) return;
    setLoadingRatings(true);
    try {
      const res = await listRatings(user.id);
      setRatings(res ?? []);
    } catch (err) {
      console.error("Failed to fetch ratings:", err);
    } finally {
      setLoadingRatings(false);
    }
  }, [user]);

  useEffect(() => {
    if (!user) return;
    void fetchFavorites();
    void fetchRatings();
  }, [user, fetchFavorites, fetchRatings]);

  const handleRemove = useCallback(
    async (show: Show) => {
      if (!user) return;
      const tmdb = getTmdbId(show);
      if (!tmdb) return;

      try {
        await removeFavorite(user.id, tmdb);
        setList((prev) => prev.filter((s) => getTmdbId(s) !== tmdb));
      } catch (err) {
        console.error("Failed to remove favourite:", err);
      }
    },
    [user],
  );

  const handleRate = useCallback(
    async (show: Show, rating: number) => {
      if (!user) return;
      const tmdb = getTmdbId(show);
      if (!tmdb) return;

      try {
        await upsertRating(user.id, {
          tmdb_id: tmdb,
          rating,
          title: (show as any).title ?? (show as any).name ?? "",
        });

        setRatings((prev) => {
          const existing = prev.find((r) => getTmdbId(r) === tmdb);
          if (existing) {
            return prev.map((r) =>
              getTmdbId(r) === tmdb ? { ...r, rating } : r,
            );
          }
          return [
            ...prev,
            {
              id: Math.random(),
              user_id: user.id,
              tmdb_id: tmdb,
              rating,
              title: (show as any).title ?? (show as any).name ?? "",
              seasons_completed: null,
              notes: null,
            },
          ];
        });
      } catch (err) {
        console.error("Failed to save rating:", err);
      }
    },
    [user],
  );

  const handleRequireLogin = useCallback(() => {
    navigate("/login");
  }, [navigate]);

  if (!user) {
    return (
      <div className="pb-10">
        <PageHeader
          title="Favourites"
          subtitle="Sign in to save your favourite shows and improve recommendations."
          centered
        />
        <div className="max-w-screen-2xl mx-auto pt-[160px] px-4 md:px-8">
          <div className="rounded-xl bg-slate-900/70 border border-slate-700/70 p-6 text-center">
            <p className="text-slate-200 mb-4">
              You need to sign in to manage favourites.
            </p>
            <button
              type="button"
              onClick={handleRequireLogin}
              className="inline-flex items-center justify-center rounded-full px-6 py-2 text-base font-semibold text-white border border-cyan-400 bg-cyan-500/90 shadow-[0_0_20px_rgba(34,211,238,0.9)] hover:bg-cyan-400 transition-colors"
            >
              Sign in
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="pb-10">
      <PageHeader
        title="Favourites"
        subtitle="Shows you’ve starred. Use ratings to tweak your recommendation profile."
        centered
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

      <div className="max-w-screen-2xl mx-auto pt-[160px] px-4 md:px-8">
        {loading ? (
          <p className="text-slate-300 text-lg">Loading…</p>
        ) : list.length === 0 ? (
          <p className="text-sm text-slate-400">No favourites yet.</p>
        ) : (
          <div className="tile-grid">
            {list.map((s) => {
              const tmdb = getTmdbId(s) ?? undefined;
              const key = String(tmdb ?? Math.random());
              const myRating = tmdb ? ratingsMap[tmdb] : undefined;
            
          
              return (
                <ShowCard
                  key={key}
                  show={{
                    ...s,
                    poster_url: posterUrl(s),
                  }}
                  myRating={myRating?.rating}
                  isFav={true}
                  onToggleFav={() => handleRemove(s)}
                  onRate={(r) => handleRate(s, r)}
                  variant={tileVariant}
                />
              );
            })}
          </div>
        )}

        {loadingRatings && (
          <p className="mt-4 text-xs text-slate-500">
            Loading your ratings…
          </p>
        )}
      </div>
    </div>
  );
}

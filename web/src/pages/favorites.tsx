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

function getAuthHeaders(): Record<string, string> {
  const h: Record<string, string> = {};
  const token = window.localStorage.getItem("access_token");
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

function getTmdbId(any: any): number | null {
  const cand = any?.tmdb_id ?? any?.external_id ?? any?.id ?? any?.show_id;
  const n = Number(cand);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function posterUrl(s: any): string | undefined {
  const p = s?.poster_url ?? s?.poster_path;
  if (!p) return undefined;
  if (typeof p === "string" && p.startsWith("http")) return p;
  return `${TMDB_IMG}${p}`;
}

export default function FavoritesPage() {
  const { user } = useAuth();
  const userId = user?.id ?? 0;
  const navigate = useNavigate();

  const [tileVariant, setTileVariant] = useState<"poster" | "glass">("poster");

  const [favorites, setFavorites] = useState<Show[]>([]);
  const [watchSet, setWatchSet] = useState<Set<number>>(new Set());
  const [ratings, setRatings] = useState<UserRating[]>([]);

  const [loadingFavs, setLoadingFavs] = useState(false);
  const [loadingRatings, setLoadingRatings] = useState(false);

  const ratingsMap = useMemo(() => {
    const map: Record<number, UserRating> = {};
    for (const r of ratings) {
      const id = (r as any).tmdb_id as number | undefined;
      if (id) map[id] = r;
    }
    return map;
  }, [ratings]);

  // load favourites + ratings
  useEffect(() => {
    let alive = true;

    async function run() {
      if (!userId) return;

      try {
        setLoadingFavs(true);
        setLoadingRatings(true);

        const [favs, rs] = await Promise.all([
          listFavoriteShows(userId),
          listRatings(userId),
        ]);

        if (!alive) return;
        setFavorites(favs ?? []);
        setRatings(rs ?? []);
      } finally {
        if (!alive) return;
        setLoadingFavs(false);
        setLoadingRatings(false);
      }
    }

    void run();
    return () => {
      alive = false;
    };
  }, [userId]);

  // watchlist ids
  useEffect(() => {
    if (!userId) {
      setWatchSet(new Set());
      return;
    }
    let alive = true;
    async function run() {
      try {
        const res = await fetch(`/api/users/${userId}/watchlist`, {
          headers: getAuthHeaders(),
        });
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        if (!alive) return;

        const ids = new Set<number>();
        (Array.isArray(data) ? data : []).forEach((x: any) => {
          const t = Number(x.tmdb_id ?? x.external_id ?? x.show_id);
          if (Number.isFinite(t) && t > 0) ids.add(t);
        });
        setWatchSet(ids);
      } catch {
        if (!alive) return;
        setWatchSet(new Set());
      }
    }
    void run();
    return () => {
      alive = false;
    };
  }, [userId]);

  /* ---- handlers ---- */

  const handleRemove = useCallback(
    async (show: Show) => {
      if (!userId) return;
      const tmdb = getTmdbId(show);
      if (!tmdb) return;

      // optimistic
      setFavorites((prev) => prev.filter((s) => getTmdbId(s) !== tmdb));

      try {
        await removeFavorite(userId, tmdb);
      } catch (e) {
        console.error("Failed to remove favourite", e);
      }
    },
    [userId],
  );

  const handleRate = useCallback(
    async (show: Show, rating: number) => {
      if (!userId) return;
      const tmdb = getTmdbId(show);
      if (!tmdb) return;

      try {
        await upsertRating(userId, {
          tmdb_id: tmdb,
          rating,
          title: (show as any).title ?? (show as any).name ?? "",
        });

        setRatings((prev) => {
          const others = prev.filter((r) => (r as any).tmdb_id !== tmdb);
          return [
            ...others,
            {
              ...(prev.find((r) => (r as any).tmdb_id === tmdb) ?? {}),
              tmdb_id: tmdb,
              rating,
            } as any,
          ];
        });
      } catch (e) {
        console.error("Failed to set rating", e);
      }
    },
    [userId],
  );

  const handleToggleWatchlist = useCallback(
    async (show: any) => {
      if (!userId) return;
      const tmdbId = Number(
        (show as any).tmdb_id ?? (show as any).external_id ?? (show as any).show_id,
      );
      if (!Number.isFinite(tmdbId) || tmdbId <= 0) return;

      const isIn = watchSet.has(tmdbId);

      // optimistic
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
      } catch {
        // revert
        setWatchSet((prev) => {
          const next = new Set(prev);
          isIn ? next.add(tmdbId) : next.delete(tmdbId);
          return next;
        });
      }
    },
    [userId, watchSet],
  );

  /* ---- render ---- */

  if (!userId) {
    return (
      <div className="pb-10">
        <PageHeader title="Favourites" subtitle="Sign in to view your favourites." centered />
      </div>
    );
  }

  return (
    <div className="pb-10">
      <PageHeader
        title="Favourites"
        subtitle="Your favourite shows. Rate them to improve recommendations."
        centered
      />

      <div className="max-w-screen-2xl mx-auto px-4 md:px-8 mt-3 flex justify-end">
        <div className="inline-flex items-center gap-2 rounded-full border border-slate-600/70 bg-slate-900/70 px-3 py-1 text-xs text-slate-200">
          <span className="uppercase tracking-[0.18em] text-[10px] text-slate-400">
            Tile style
          </span>

          <span className="mx-1 h-4 w-px bg-slate-600/70" aria-hidden="true" />

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

      <div className="mx-auto max-w-7xl px-4 pb-10" style={{ paddingTop: "140px" }}>
        {loadingFavs ? (
          <div className="text-sm text-slate-400">Loading favourites…</div>
        ) : favorites.length === 0 ? (
          <div className="text-sm text-slate-400">
            No favourites yet. Go to Discover and tap the heart.
          </div>
        ) : (
          <div className="tile-grid">
            {favorites.map((s) => {
              const tmdb = getTmdbId(s) ?? undefined;
              const key = String(tmdb ?? (s as any).show_id ?? Math.random());
              const myRating = tmdb ? ratingsMap[tmdb] : undefined;
              const isWatchlist = tmdb ? watchSet.has(tmdb) : false;

              return (
                <ShowCard
                  key={key}
                  show={{ ...s, poster_url: posterUrl(s) }}
                  myRating={myRating?.rating}
                  isFav={true}
                  onToggleFav={() => handleRemove(s)}
                  isWatchlist={isWatchlist}
                  onToggleWatchlist={() => handleToggleWatchlist(s)}
                  onRate={(r) => handleRate(s, r)}
                  variant={tileVariant}
                />
              );
            })}
          </div>
        )}

        {loadingRatings && (
          <div className="mt-4 text-xs text-slate-500">
            Loading ratings…
          </div>
        )}
      </div>
    </div>
  );
}

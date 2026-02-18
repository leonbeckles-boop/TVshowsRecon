import React, { useEffect, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import ShowCard from "../components/ShowCard";
import { useAuth } from "../auth/AuthProvider";

type WatchItem = any;

function getAuthHeaders(): Record<string, string> {
  const h: Record<string, string> = {};
  const token = localStorage.getItem("access_token");
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

function getTmdbId(x: any): number | null {
  const cand = x?.tmdb_id ?? x?.external_id ?? x?.show_id ?? x?.id;
  const n = Number(cand);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export default function Watchlist() {
  const { user } = useAuth();
  const userId = user?.id;

  const [items, setItems] = useState<WatchItem[]>([]);
  const [favSet, setFavSet] = useState<Set<number>>(new Set());

  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const headers = useMemo(() => getAuthHeaders(), []);

  const load = async () => {
    if (!userId) return;
    setLoading(true);
    setErr(null);
    try {
      // load watchlist + favorites (for heart state)
      const [wlRes, favRes] = await Promise.all([
        fetch(`/api/users/${userId}/watchlist`, { headers }),
        fetch(`/api/users/${userId}/favorites`, { headers }),
      ]);

      if (!wlRes.ok) throw new Error(`Watchlist failed: ${wlRes.status}`);
      if (!favRes.ok) throw new Error(`Favorites failed: ${favRes.status}`);

      const wlData = await wlRes.json();
      const favData = await favRes.json();

      setItems(Array.isArray(wlData) ? wlData : []);

      const favIds = new Set<number>();
      (Array.isArray(favData) ? favData : []).forEach((s: any) => {
        const id = getTmdbId(s);
        if (id) favIds.add(id);
      });
      setFavSet(favIds);
    } catch (e: any) {
      setErr(e?.message ?? "Failed to load watchlist");
      setItems([]);
    } finally {
      setLoading(false);
    }
  };

  const removeFromWatchlist = async (tmdbId: number) => {
    if (!userId) return;
    // optimistic UI
    setItems((prev) => prev.filter((x) => getTmdbId(x) !== tmdbId));

    const res = await fetch(`/api/users/${userId}/watchlist/${tmdbId}`, {
      method: "DELETE",
      headers,
    });
    if (!res.ok) {
      // revert by reloading truth
      await load();
      throw new Error(`Remove watchlist failed: ${res.status}`);
    }
  };

  const addToFavorites = async (tmdbId: number) => {
    if (!userId) return;
    const res = await fetch(`/api/users/${userId}/favorites/${tmdbId}`, {
      method: "POST",
      headers,
    });
    if (!res.ok) throw new Error(`Add favorite failed: ${res.status}`);
    setFavSet((prev) => new Set(prev).add(tmdbId));
  };

  const addToNotInterested = async (tmdbId: number) => {
    if (!userId) return;
    // Your backend route earlier looked like /api/users/{id}/not-interested/{tmdb}
    // If yours differs, tell me the exact path from /api/docs and I’ll adjust.
    const res = await fetch(`/api/users/${userId}/not-interested/${tmdbId}`, {
      method: "POST",
      headers,
    });
    if (!res.ok) throw new Error(`Not interested failed: ${res.status}`);
  };

  // ✅ Favorite: remove from watchlist + add to favorites
  const handleFavFromWatchlist = async (tmdbId: number) => {
    try {
      await Promise.all([
        addToFavorites(tmdbId),
        removeFromWatchlist(tmdbId),
      ]);
    } catch (e) {
      console.error(e);
    }
  };

  // ✅ Not interested: remove from watchlist + mark not interested
  const handleHideFromWatchlist = async (tmdbId: number) => {
    try {
      await Promise.all([
        addToNotInterested(tmdbId),
        removeFromWatchlist(tmdbId),
      ]);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  return (
    <div className="min-h-screen bg-[#020617] text-slate-100">
      <PageHeader title="Watchlist" subtitle="Shows you want to watch next" />

      <div className="pt-[120px] px-4 md:px-8 pb-8">
        {!userId ? (
          <div className="max-w-xl mx-auto rounded-2xl border border-white/10 bg-white/5 p-6">
            <div className="text-lg font-semibold">Sign in required</div>
            <div className="mt-2 text-sm opacity-80">
              Please sign in to view your watchlist.
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm opacity-80">
                {items.length} show{items.length === 1 ? "" : "s"}
              </div>
              <button
                onClick={load}
                disabled={loading}
                className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold hover:bg-white/10 disabled:opacity-60"
              >
                {loading ? "Refreshing..." : "Refresh"}
              </button>
            </div>

            {err && (
              <div className="mt-4 rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm">
                {err}
              </div>
            )}

            {!loading && items.length === 0 ? (
              <div className="mt-6 rounded-2xl border border-white/10 bg-white/5 p-6">
                <div className="text-lg font-semibold">Your watchlist is empty</div>
                <div className="mt-2 text-sm opacity-80">
                  Add shows to your watchlist from Discover/Search using the 🔖 button.
                </div>
              </div>
            ) : (
              <div
                className="mt-6 grid gap-4"
                style={{ gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}
              >
                {items.map((show) => {
                  const tmdbId = getTmdbId(show);
                  if (!tmdbId) return null;

                  const isFav = favSet.has(tmdbId);

                  return (
                    <ShowCard
                      key={tmdbId}
                      show={show}
                      // show all 3 buttons on watchlist page
                      isFav={isFav}
                      onToggleFav={() => handleFavFromWatchlist(tmdbId)}
                      onHide={() => handleHideFromWatchlist(tmdbId)}
                      isWatchlist={true}
                      onToggleWatchlist={() => removeFromWatchlist(tmdbId)}
                    />
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

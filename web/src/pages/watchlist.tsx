import React, { useEffect, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import ShowCard from "../components/ShowCard";
import { useAuth } from "../auth/AuthProvider";

type WatchItem = any;

export default function Watchlist() {
  const { user } = useAuth();
  const userId = user?.id;

  const [items, setItems] = useState<WatchItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const headers = useMemo(() => {
    const h: Record<string, string> = {};
    const token = localStorage.getItem("access_token"); // ✅ matches your AuthProvider.tsx
    if (token) h["Authorization"] = `Bearer ${token}`;
    return h;
  }, []);

  const load = async () => {
    if (!userId) return;
    setLoading(true);
    setErr(null);
    try {
      const res = await fetch(`/api/users/${userId}/watchlist`, { headers });
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      const data = await res.json();
      setItems(Array.isArray(data) ? data : []);
    } catch (e: any) {
      setErr(e?.message ?? "Failed to load watchlist");
    } finally {
      setLoading(false);
    }
  };

  const toggleWatchlist = async (tmdbId: number, isInWatchlist: boolean) => {
    if (!userId) return;

    // optimistic UI
    setItems((prev) => {
      if (isInWatchlist) {
        return prev.filter((x) => Number(x?.tmdb_id ?? x?.show_id) !== tmdbId);
      }
      return [{ tmdb_id: tmdbId, show_id: tmdbId, title: `TMDb #${tmdbId}` }, ...prev];
    });

    try {
      const url = `/api/users/${userId}/watchlist/${tmdbId}`;
      const res = await fetch(url, {
        method: isInWatchlist ? "DELETE" : "POST",
        headers,
      });
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
    } catch {
      // revert to server truth if anything failed
      load();
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
                  const tmdbId = Number(show?.tmdb_id ?? show?.show_id);
                  return (
                    <ShowCard
                      key={tmdbId}
                      show={show}
                      isWatchlist={true}
                      onToggleWatchlist={() => toggleWatchlist(tmdbId, true)}
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

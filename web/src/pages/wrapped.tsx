import React, { useEffect, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import { useAuth } from "../auth/AuthProvider";

type Show = {
  tmdb_id?: number;
  show_id?: number;
  external_id?: number;
  id?: number;
  title?: string;
  name?: string;
  poster_path?: string | null;
  poster_url?: string | null;
  [key: string]: any;
};

function getAuthHeaders(): Record<string, string> {
  const h: Record<string, string> = {};
  const token = window.localStorage.getItem("access_token");
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

function fmt(n: number) {
  return new Intl.NumberFormat().format(n);
}

function clamp01(x: number) {
  return Math.max(0, Math.min(1, x));
}

export default function Wrapped() {
  const { user } = useAuth();
  const userId = user?.id ?? null;

  const [favorites, setFavorites] = useState<Show[]>([]);
  const [watchlist, setWatchlist] = useState<Show[]>([]);
  const [hidden, setHidden] = useState<Show[]>([]);
  const [ratings, setRatings] = useState<any[]>([]);

  const [genreProfile, setGenreProfile] = useState<{ genre: string; count: number }[]>([]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const headers = useMemo(() => getAuthHeaders(), []);

  useEffect(() => {
    if (!userId) return;

    let alive = true;
    setLoading(true);
    setError(null);

    const loadAll = async () => {
      try {
        const [favRes, rateRes, watchRes, hiddenRes, genreRes] = await Promise.all([
          fetch(`/api/users/${userId}/favorites`, { headers }),
          fetch(`/api/ratings/ratings?user_id=${userId}`, { headers }),
          fetch(`/api/users/${userId}/watchlist`, { headers }),
          fetch(`/api/users/${userId}/not-interested`, { headers }),
          fetch(`/api/users/${userId}/genre-profile?limit=60`, { headers }),
        ]);

        if (!favRes.ok) throw new Error(`Favorites failed: ${favRes.status}`);
        if (!rateRes.ok) throw new Error(`Ratings failed: ${rateRes.status}`);
        if (!watchRes.ok) throw new Error(`Watchlist failed: ${watchRes.status}`);
        if (!hiddenRes.ok) throw new Error(`Hidden failed: ${hiddenRes.status}`);
        // genre-profile can fail gracefully (don’t block whole page)
        const favData = await favRes.json();
        const rateData = await rateRes.json();
        const watchData = await watchRes.json();
        const hiddenData = await hiddenRes.json();

        let gp: any = null;
        try {
          gp = genreRes.ok ? await genreRes.json() : null;
        } catch {
          gp = null;
        }

        if (!alive) return;

        setFavorites(Array.isArray(favData) ? favData : []);
        setRatings(Array.isArray(rateData) ? rateData : []);
        setWatchlist(Array.isArray(watchData) ? watchData : []);
        setHidden(Array.isArray(hiddenData) ? hiddenData : []);

        const top = Array.isArray(gp?.top_genres) ? gp.top_genres : [];
        setGenreProfile(
          top
            .map((x: any) => ({ genre: String(x?.genre ?? ""), count: Number(x?.count ?? 0) }))
            .filter((x: any) => x.genre && Number.isFinite(x.count) && x.count > 0),
        );
      } catch (e: any) {
        if (!alive) return;
        setError(e?.message ?? "Failed to load Wrapped");
      } finally {
        if (alive) setLoading(false);
      }
    };

    void loadAll();

    return () => {
      alive = false;
    };
  }, [userId, headers]);

  const favCount = favorites.length;
  const watchCount = watchlist.length;
  const hiddenCount = hidden.length;
  const ratedCount = ratings.length;

  const avgRating = useMemo(() => {
    const nums = ratings.map((r) => Number(r?.rating)).filter((x) => Number.isFinite(x));
    if (!nums.length) return null;
    const sum = nums.reduce((a, b) => a + b, 0);
    return Math.round((sum / nums.length) * 10) / 10;
  }, [ratings]);

  const topGenre = genreProfile[0]?.genre ?? "Mixed";

  const confidence = useMemo(() => {
    const signals = favCount + watchCount + ratedCount;
    if (signals >= 20) return "HIGH";
    if (signals >= 10) return "MEDIUM";
    return "LOW";
  }, [favCount, watchCount, ratedCount]);

  const totalTracked = favCount + watchCount + ratedCount;

  // ----- Styles -----
  const pageWrap: React.CSSProperties = {
    paddingTop: 120,
    paddingLeft: 16,
    paddingRight: 16,
    paddingBottom: 40,
    maxWidth: 1180,
    margin: "0 auto",
  };

  const glass: React.CSSProperties = {
    borderRadius: 18,
    border: "1px solid rgba(255,255,255,0.10)",
    background: "rgba(255,255,255,0.04)",
    boxShadow: "0 10px 40px rgba(0,0,0,0.35)",
    backdropFilter: "blur(8px)",
  };

  const h1: React.CSSProperties = { fontSize: 34, margin: 0 };
  const sub: React.CSSProperties = { opacity: 0.8, marginTop: 6 };

  const grid: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
    gap: 14,
    marginTop: 18,
  };

  const metricCard: React.CSSProperties = {
    ...glass,
    padding: 16,
    minHeight: 92,
  };

  const metricLabel: React.CSSProperties = { opacity: 0.75, fontSize: 12, letterSpacing: 0.8 };
  const metricValue: React.CSSProperties = { fontSize: 28, fontWeight: 700, marginTop: 6 };

  const sectionCard: React.CSSProperties = {
    ...glass,
    padding: 18,
    marginTop: 16,
  };

  const sectionTitle: React.CSSProperties = { fontSize: 18, margin: 0, marginBottom: 12 };

  const pill: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    padding: "8px 12px",
    borderRadius: 999,
    border: "1px solid rgba(255,255,255,0.12)",
    background: "rgba(255,255,255,0.06)",
    fontSize: 13,
  };

  const barRow: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: "140px 1fr 40px",
    gap: 10,
    alignItems: "center",
    padding: "6px 0",
  };

  const barOuter: React.CSSProperties = {
    height: 10,
    borderRadius: 999,
    background: "rgba(255,255,255,0.10)",
    overflow: "hidden",
  };

  const barInner = (pct: number): React.CSSProperties => ({
    height: "100%",
    width: `${Math.round(clamp01(pct) * 100)}%`,
    borderRadius: 999,
    background: "rgba(56,189,248,0.75)",
  });

  return (
    <div>
      <PageHeader title="Your WhatNext Wrapped" subtitle="A cinematic recap of your TV taste and habits." />

      <div style={pageWrap}>
        <div style={{ ...pill, marginBottom: 10 }}>Wrapped v3 ✅</div>

        {error && (
          <div style={{ ...glass, padding: 14, borderColor: "rgba(255,0,0,0.25)" }}>{error}</div>
        )}

        <div style={{ ...glass, padding: 18 }}>
          <div style={h1}>Your TV year in review</div>
          <div style={sub}>Here’s how your taste shaped up — from the shows you saved to what you queued next.</div>

          {loading && <div style={{ marginTop: 10, opacity: 0.75 }}>Loading…</div>}

          <div style={grid}>
            <div style={metricCard}>
              <div style={metricLabel}>SHOWS RATED</div>
              <div style={metricValue}>{fmt(ratedCount)}</div>
              <div style={{ opacity: 0.7, marginTop: 2 }}>Avg rating: {avgRating == null ? "—" : avgRating}</div>
            </div>

            <div style={metricCard}>
              <div style={metricLabel}>FAVOURITES</div>
              <div style={metricValue}>{fmt(favCount)}</div>
              <div style={{ opacity: 0.7, marginTop: 2 }}>Top genre: {topGenre}</div>
            </div>

            <div style={metricCard}>
              <div style={metricLabel}>WATCHLIST</div>
              <div style={metricValue}>{fmt(watchCount)}</div>
              <div style={{ opacity: 0.7, marginTop: 2 }}>Queued to watch next</div>
            </div>

            <div style={metricCard}>
              <div style={metricLabel}>HIDDEN</div>
              <div style={metricValue}>{fmt(hiddenCount)}</div>
              <div style={{ opacity: 0.7, marginTop: 2 }}>Not interested / filtered</div>
            </div>
          </div>
        </div>

        <div style={sectionCard}>
          <h2 style={sectionTitle}>Taste Profile</h2>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            <div style={pill}>
              Recommendation confidence: <strong>{confidence}</strong>
            </div>
            <div style={pill}>
              Total tracked: <strong>{fmt(totalTracked)}</strong>
            </div>
            <div style={pill}>
              Signals: <strong>{fmt(favCount + watchCount + ratedCount)}</strong>
            </div>
          </div>

          <div style={{ marginTop: 14, opacity: 0.85, lineHeight: 1.7 }}>
            Based on <strong>{favCount}</strong> favourites, <strong>{ratedCount}</strong> ratings, and{" "}
            <strong>{watchCount}</strong> watchlist items.
          </div>
        </div>

        <div style={sectionCard}>
          <h2 style={sectionTitle}>Genre spread</h2>

          {genreProfile.length === 0 ? (
            <div style={{ opacity: 0.8 }}>
              Genre spread will appear once we can read genres from TMDb (check TMDB_API_KEY) and you have favourites/watchlist.
            </div>
          ) : (
            (() => {
              const top = genreProfile.slice(0, 8);
              const max = top[0]?.count ?? 1;
              return (
                <div>
                  {top.map((g) => (
                    <div key={g.genre} style={barRow}>
                      <div style={{ opacity: 0.85 }}>{g.genre}</div>
                      <div style={barOuter}>
                        <div style={barInner(g.count / max)} />
                      </div>
                      <div style={{ textAlign: "right", opacity: 0.85 }}>{g.count}</div>
                    </div>
                  ))}
                </div>
              );
            })()
          )}
        </div>
      </div>
    </div>
  );
}

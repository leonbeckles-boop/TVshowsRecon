import React, { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "../components/PageHeader";
import ShowCard from "../components/ShowCard";
import { useAuth } from "../auth/AuthProvider";

/* ---------- Types ---------- */

type Show = {
  tmdb_id?: number;
  show_id?: number;
  external_id?: number;
  title?: string;
  name?: string;
  poster_path?: string | null;
  poster_url?: string | null;
  [key: string]: any;
};

type DiscoverSection = {
  key: string;
  title: string;
  items: Show[];
};

type DiscoverResponse = {
  featured?: Show[];
  trending?: Show[];
  top_decade?: Show[];
  genres?: Record<string, Show[]>;
};

/* ---------- Helpers ---------- */

function getTmdbId(x: any): number | null {
  const cand = x?.tmdb_id ?? x?.external_id ?? x?.show_id ?? x?.id;
  const n = Number(cand);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function getAuthHeaders(): Record<string, string> {
  const h: Record<string, string> = {};
  const token = window.localStorage.getItem("access_token");
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

function removeFromSections(prev: DiscoverSection[], tmdbId: number): DiscoverSection[] {
  return prev.map((sec) => ({
    ...sec,
    items: sec.items.filter((s) => getTmdbId(s) !== tmdbId),
  }));
}

/* ---------- Page ---------- */

export default function Discover() {
  const { user } = useAuth();
  const userId = user?.id ?? null;

  const [sections, setSections] = useState<DiscoverSection[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [favSet, setFavSet] = useState<Set<number>>(new Set());
  const [watchSet, setWatchSet] = useState<Set<number>>(new Set());

  const headers = useMemo(() => getAuthHeaders(), []);

  /* ---------- Load discover (backend filters when user_id present) ---------- */

  useEffect(() => {
    let alive = true;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const url = userId ? `/api/discover?user_id=${userId}` : "/api/discover";
        const res = await fetch(url, { headers });
        if (!res.ok) throw new Error(`Discover failed: ${res.status}`);
        const data: DiscoverResponse = await res.json();
        if (!alive) return;

        // UI order you want:
        // 1) New & Trending (data.featured is already remapped server-side)
        // 2) Top Featured (data.top_decade is already remapped server-side)
        // 3) Trending Now (data.trending is already remapped server-side)
        const next: DiscoverSection[] = [
          { key: "featured", title: "New & Trending", items: data.featured ?? [] },
          { key: "top_decade", title: "Top Featured", items: data.top_decade ?? [] },
          { key: "trending", title: "Trending Now", items: data.trending ?? [] },
        ];

        if (data.genres) {
          Object.entries(data.genres).forEach(([genre, items]) => {
            next.push({ key: `genre:${genre}`, title: genre, items: items ?? [] });
          });
        }

        setSections(next);
      } catch (e: any) {
        if (!alive) return;
        setError(e?.message ?? "Failed to load Discover");
        setSections([]);
      } finally {
        if (alive) setLoading(false);
      }
    };

    void load();
    return () => {
      alive = false;
    };
  }, [userId, headers]);

  /* ---------- Load favorites set ---------- */

  useEffect(() => {
    if (!userId) {
      setFavSet(new Set());
      return;
    }
    let alive = true;

    const loadFavs = async () => {
      try {
        const res = await fetch(`/api/users/${userId}/favorites`, { headers });
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();

        const ids = new Set<number>();
        (Array.isArray(data) ? data : []).forEach((x: any) => {
          const id = getTmdbId(x);
          if (id) ids.add(id);
        });

        if (alive) setFavSet(ids);
      } catch {
        if (alive) setFavSet(new Set());
      }
    };

    void loadFavs();
    return () => {
      alive = false;
    };
  }, [userId, headers]);

  /* ---------- Load watchlist set ---------- */

  useEffect(() => {
    if (!userId) {
      setWatchSet(new Set());
      return;
    }
    let alive = true;

    const loadWatch = async () => {
      try {
        const res = await fetch(`/api/users/${userId}/watchlist`, { headers });
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();

        const ids = new Set<number>();
        (Array.isArray(data) ? data : []).forEach((x: any) => {
          const id = getTmdbId(x);
          if (id) ids.add(id);
        });

        if (alive) setWatchSet(ids);
      } catch {
        if (alive) setWatchSet(new Set());
      }
    };

    void loadWatch();
    return () => {
      alive = false;
    };
  }, [userId, headers]);

  /* ---------- Actions ---------- */

  const handleToggleFav = useCallback(
    async (show: Show) => {
      if (!userId) return;
      const tmdbId = getTmdbId(show);
      if (!tmdbId) return;

      const isFav = favSet.has(tmdbId);

      // optimistic
      setFavSet((prev) => {
        const next = new Set(prev);
        isFav ? next.delete(tmdbId) : next.add(tmdbId);
        return next;
      });

      // if adding to favs, remove from discover immediately
      if (!isFav) setSections((prev) => removeFromSections(prev, tmdbId));

      try {
        const res = await fetch(`/api/users/${userId}/favorites/${tmdbId}`, {
          method: isFav ? "DELETE" : "POST",
          headers,
        });
        if (!res.ok) throw new Error(String(res.status));
      } catch (e) {
        // revert
        setFavSet((prev) => {
          const next = new Set(prev);
          isFav ? next.add(tmdbId) : next.delete(tmdbId);
          return next;
        });
      }
    },
    [userId, favSet, headers],
  );

  const handleToggleWatchlist = useCallback(
    async (show: Show) => {
      if (!userId) return;
      const tmdbId = getTmdbId(show);
      if (!tmdbId) return;

      const isIn = watchSet.has(tmdbId);

      // optimistic
      setWatchSet((prev) => {
        const next = new Set(prev);
        isIn ? next.delete(tmdbId) : next.add(tmdbId);
        return next;
      });

      // if adding to watchlist, remove from discover immediately
      if (!isIn) setSections((prev) => removeFromSections(prev, tmdbId));

      try {
        const res = await fetch(`/api/users/${userId}/watchlist/${tmdbId}`, {
          method: isIn ? "DELETE" : "POST",
          headers,
        });
        if (!res.ok) throw new Error(String(res.status));
      } catch (e) {
        // revert
        setWatchSet((prev) => {
          const next = new Set(prev);
          isIn ? next.add(tmdbId) : next.delete(tmdbId);
          return next;
        });
      }
    },
    [userId, watchSet, headers],
  );

  const handleHide = useCallback(
    async (show: Show) => {
      if (!userId) return;
      const tmdbId = getTmdbId(show);
      if (!tmdbId) return;

      // optimistic: remove from grid immediately
      setSections((prev) => removeFromSections(prev, tmdbId));

      try {
        const res = await fetch(`/api/users/${userId}/not-interested/${tmdbId}`, {
          method: "POST",
          headers,
        });
        if (!res.ok) throw new Error(String(res.status));
      } catch (e) {
        console.error("Failed to mark not-interested from Discover", e);
      }
    },
    [userId, headers],
  );

  /* ---------- Render ---------- */

  return (
    <div>
      <PageHeader title="Discover" subtitle="Find something new to watch" />

      <div style={{ paddingTop: 120, paddingLeft: 16, paddingRight: 16, paddingBottom: 24 }}>
        {error && (
          <div
            style={{
              marginBottom: 16,
              padding: 12,
              borderRadius: 12,
              border: "1px solid rgba(255,0,0,0.35)",
              background: "rgba(255,0,0,0.08)",
            }}
          >
            {error}
          </div>
        )}

        {loading && <div style={{ opacity: 0.8 }}>Loading…</div>}

        {!loading &&
          sections.map((sec) => (
            <section key={sec.key} style={{ marginBottom: 28 }}>
              <h2 style={{ fontSize: 22, marginBottom: 12 }}>{sec.title}</h2>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
                  gap: 18,
                }}
              >
                {sec.items.map((show) => {
                  const tmdbId = getTmdbId(show);
                  const key = tmdbId ? `tmdb:${tmdbId}` : JSON.stringify(show);

                  const isFav = tmdbId ? favSet.has(tmdbId) : false;
                  const isWatchlist = tmdbId ? watchSet.has(tmdbId) : false;

                  return (
                    <ShowCard
                      key={key}
                      show={show}
                      isFav={isFav}
                      onToggleFav={userId ? () => handleToggleFav(show) : undefined}
                      isWatchlist={isWatchlist}
                      onToggleWatchlist={userId ? () => handleToggleWatchlist(show) : undefined}
                      onHide={userId ? () => handleHide(show) : undefined}
                    />
                  );
                })}
              </div>
            </section>
          ))}
      </div>
    </div>
  );
}

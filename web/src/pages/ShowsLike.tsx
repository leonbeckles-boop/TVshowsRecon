import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiUrl } from "../api";
import { useAuth } from "../auth/AuthProvider";
import ShowCard from "../components/ShowCard";

type SeoAnchor = {
  tmdb_id: number;
  title: string;
  poster_path?: string | null;
};

type SeoRec = {
  tmdb_id: number;
  title: string;
  poster_path?: string | null;
  overview?: string | null;
  source?: string;
};

function slugifyTitle(title: string): string {
  return String(title || "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

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

export default function ShowsLike() {
  const { slug } = useParams();
  const { user } = useAuth();
  const userId = user?.id ?? null;

  const [anchor, setAnchor] = useState<SeoAnchor | null>(null);
  const [recs, setRecs] = useState<SeoRec[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [favSet, setFavSet] = useState<Set<number>>(new Set());
  const [watchSet, setWatchSet] = useState<Set<number>>(new Set());

  const headers = useMemo(() => getAuthHeaders(), []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(null);

        const r = await fetch(apiUrl(`/seo/shows-like/${slug}`));
        if (!r.ok) {
          throw new Error(`Failed to load page (${r.status})`);
        }

        const data = await r.json();

        if (cancelled) return;

        setAnchor(data.anchor ?? null);
        setRecs(Array.isArray(data.recommendations) ? data.recommendations : []);
      } catch (err: any) {
        if (cancelled) return;
        setError(err?.message || "Failed to load recommendations.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    if (slug) {
      void load();
    }

    return () => {
      cancelled = true;
    };
  }, [slug]);

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

  useEffect(() => {
    if (!anchor?.title || !slug) return;

    const pageTitle = `Shows Like ${anchor.title} | WhatNext`;
    const pageDescription = `Looking for shows like ${anchor.title}? Discover similar TV series to watch next with WhatNext.`;

    document.title = pageTitle;

    let meta = document.querySelector('meta[name="description"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "description");
      document.head.appendChild(meta);
    }
    meta.setAttribute("content", pageDescription);

    let canonical = document.querySelector('link[rel="canonical"]');
    if (!canonical) {
      canonical = document.createElement("link");
      canonical.setAttribute("rel", "canonical");
      document.head.appendChild(canonical);
    }
    canonical.setAttribute(
      "href",
      `${window.location.origin}/shows-like/${slug}`
    );
  }, [anchor, slug]);

  const handleToggleFav = async (show: any) => {
    if (!userId) return;
    const tmdbId = getTmdbId(show);
    if (!tmdbId) return;

    const isFav = favSet.has(tmdbId);

    setFavSet((prev) => {
      const next = new Set(prev);
      isFav ? next.delete(tmdbId) : next.add(tmdbId);
      return next;
    });

    try {
      await fetch(`/api/users/${userId}/favorites/${tmdbId}`, {
        method: isFav ? "DELETE" : "POST",
        headers,
      });
    } catch {}
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
      await fetch(`/api/users/${userId}/watchlist/${tmdbId}`, {
        method: isIn ? "DELETE" : "POST",
        headers,
      });
    } catch {}
  };

  const handleHide = async (show: any) => {
    if (!userId) return;
    const tmdbId = getTmdbId(show);
    if (!tmdbId) return;

    setRecs((prev) => prev.filter((r) => r.tmdb_id !== tmdbId));

    try {
      await fetch(`/api/users/${userId}/not-interested/${tmdbId}`, {
        method: "POST",
        headers,
      });
    } catch {}
  };

  const relatedPages = useMemo(() => {
    return recs
      .filter((r) => r?.title)
      .slice(0, 6)
      .map((r) => ({
        title: r.title,
        slug: slugifyTitle(r.title),
      }));
  }, [recs]);

  if (!slug) {
    return (
      <div className="page-body shows-like-page">
        <div className="glass-card admin-empty">Invalid page.</div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="page-body shows-like-page">
        <div className="glass-card admin-empty">Loading...</div>
      </div>
    );
  }

  if (error || !anchor) {
    return (
      <div className="page-body shows-like-page">
        <div className="glass-card admin-empty">
          {error || "We couldn't find that show."}
        </div>
      </div>
    );
  }

  return (
    <div className="page-body shows-like-page">
      <div className="shows-like-hero">
        <h1 className="shows-like-title">Shows Like {anchor.title}</h1>

        <p className="shows-like-intro">
          Looking for series similar to <strong>{anchor.title}</strong>? These
          recommendations are based on related viewing patterns and shows people
          often enjoy next.
        </p>
      </div>

      <div className="tile-grid">
        {recs.map((r) => {
          const show = {
            tmdb_id: r.tmdb_id,
            title: r.title,
            poster_path: r.poster_path,
            overview: r.overview,
          };

          const tmdbId = r.tmdb_id;
          const isFav = favSet.has(tmdbId);
          const isWatchlist = watchSet.has(tmdbId);

          return (
            <ShowCard
              key={tmdbId}
              show={show}
              isFav={isFav}
              isWatchlist={isWatchlist}
              onToggleFav={userId ? () => handleToggleFav(show) : undefined}
              onToggleWatchlist={
                userId ? () => handleToggleWatchlist(show) : undefined
              }
              onHide={userId ? () => handleHide(show) : undefined}
            />
          );
        })}
      </div>

      {relatedPages.length > 0 && (
        <section className="shows-like-related">
          <h2 className="shows-like-related__title">Explore more</h2>
          <div className="shows-like-related__links">
            {relatedPages.map((item) => (
              <Link
                key={item.slug}
                to={`/shows-like/${item.slug}`}
                className="shows-like-related__link"
              >
                {item.title}
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
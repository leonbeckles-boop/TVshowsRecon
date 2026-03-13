import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiUrl } from "../api";

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

export default function ShowsLike() {
  const { slug } = useParams();
  const [anchor, setAnchor] = useState<SeoAnchor | null>(null);
  const [recs, setRecs] = useState<SeoRec[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  if (!slug) {
    return (
      <div className="page-body shows-like-page">
        <div className="glass-card admin-empty">Invalid page.</div>
      </div>
    );
  }

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

    load();

    return () => {
      cancelled = true;
    };
  }, [slug]);

  useEffect(() => {
    if (!anchor?.title) return;

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

  const relatedPages = useMemo(() => {
    return recs
      .filter((r) => r?.title)
      .slice(0, 6)
      .map((r) => ({
        title: r.title,
        slug: slugifyTitle(r.title),
      }));
  }, [recs]);

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
        {recs.map((r) => (
          <Link
            key={r.tmdb_id}
            to={`/show/${r.tmdb_id}`}
            className="show-card-link"
          >
            <div className="show-card">
              {r.poster_path ? (
                <img
                  src={`https://image.tmdb.org/t/p/w500${r.poster_path}`}
                  alt={r.title}
                />
              ) : null}
              <div>{r.title}</div>
            </div>
          </Link>
        ))}
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
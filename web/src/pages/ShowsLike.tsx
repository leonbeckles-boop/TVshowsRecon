
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

function joinTitles(items: { title: string }[], max = 3): string {
  return items
    .slice(0, max)
    .map((x) => x.title)
    .filter(Boolean)
    .join(", ");
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

  const relatedPages = useMemo(() => {
    return recs
      .filter((r) => r?.title)
      .slice(0, 6)
      .map((r) => ({
        title: r.title,
        slug: slugifyTitle(r.title),
      }));
  }, [recs]);

  const topTitles = useMemo(() => joinTitles(recs, 3), [recs]);

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

  useEffect(() => {
    if (!anchor?.title) return;

    const faqSchema = {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: [
        {
          "@type": "Question",
          name: `What shows are similar to ${anchor.title}?`,
          acceptedAnswer: {
            "@type": "Answer",
            text: topTitles
              ? `If you liked ${anchor.title}, shows such as ${topTitles} are strong alternatives. They share similar themes, tone or storytelling style.`
              : `WhatNext helps viewers discover similar TV series to ${anchor.title}.`,
          },
        },
        {
          "@type": "Question",
          name: `What should I watch after ${anchor.title}?`,
          acceptedAnswer: {
            "@type": "Answer",
            text: topTitles
              ? `A good next watch after ${anchor.title} depends on what you enjoyed most about it. ${topTitles} are all strong follow‑up choices.`
              : `WhatNext recommends TV series with similar storytelling and themes to ${anchor.title}.`,
          },
        },
        {
          "@type": "Question",
          name: `Where can I find more shows like ${anchor.title}?`,
          acceptedAnswer: {
            "@type": "Answer",
            text: `You can browse recommendations, save favourites and build a watchlist on WhatNext.`,
          },
        },
      ],
    };

    const existing = document.getElementById("shows-like-faq-schema");
    if (existing) existing.remove();

    const script = document.createElement("script");
    script.id = "shows-like-faq-schema";
    script.type = "application/ld+json";
    script.text = JSON.stringify(faqSchema);
    document.head.appendChild(script);
  }, [anchor, topTitles]);

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

        {topTitles && (
          <p className="shows-like-seo">
            If you enjoyed <strong>{anchor.title}</strong>, you may also like{" "}
            <strong>{topTitles}</strong>. These shows share similar storytelling,
            characters and themes.
          </p>
        )}
      </div>

      <div className="tile-grid">
        {recs.map((r) => (
          <ShowCard key={r.tmdb_id} show={r} />
        ))}
      </div>

      <section className="shows-like-faq">
        <h2 className="shows-like-faq__title">Frequently asked questions</h2>

        <div className="shows-like-faq__item">
          <h3>What shows are similar to {anchor.title}?</h3>
          <p>
            If you liked {anchor.title}, shows such as {topTitles} share similar
            themes, tone and storytelling style.
          </p>
        </div>

        <div className="shows-like-faq__item">
          <h3>What should I watch after {anchor.title}?</h3>
          <p>
            A good next watch after {anchor.title} could be {topTitles}. These
            series are often recommended next by viewers.
          </p>
        </div>

        <div className="shows-like-faq__item">
          <h3>Where can I find more shows like {anchor.title}?</h3>
          <p>
            Browse recommendations, save favourites and build a watchlist on
            WhatNext to discover more TV shows like {anchor.title}.
          </p>
        </div>
      </section>

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

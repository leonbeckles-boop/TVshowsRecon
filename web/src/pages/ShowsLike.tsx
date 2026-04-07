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
  genres?: string[];
  genre_ids?: number[];
};

function slugifyTitle(title: string): string {
  return String(title || "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function getAuthHeaders(): Record<string, string> {
  const h: Record<string, string> = {};
  const token = window.localStorage.getItem("access_token");
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

function toTitleList(items: { title: string }[], max = 3): string[] {
  return items
    .slice(0, max)
    .map((x) => x.title)
    .filter(Boolean);
}

function joinNatural(items: string[]): string {
  const clean = items.filter(Boolean);
  if (clean.length === 0) return "";
  if (clean.length === 1) return clean[0];
  if (clean.length === 2) return `${clean[0]} and ${clean[1]}`;
  return `${clean.slice(0, -1).join(", ")}, and ${clean[clean.length - 1]}`;
}

function buildIntro(
  anchorTitle: string,
  recs: SeoRec[]
): { intro: string; seo: string } {
  const top3 = toTitleList(recs, 3);
  const topText = joinNatural(top3);

  const sources = new Set(recs.map((r) => r.source).filter(Boolean));
  const allGenres = recs.flatMap((r) => r.genres || []);
  const genreCounts = new Map<string, number>();

  for (const genre of allGenres) {
    const g = String(genre || "").trim();
    if (!g) continue;
    genreCounts.set(g, (genreCounts.get(g) || 0) + 1);
  }

  const topGenres = [...genreCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2)
    .map(([g]) => g);

  const genreText =
    topGenres.length === 2
      ? `${topGenres[0].toLowerCase()} and ${topGenres[1].toLowerCase()}`
      : topGenres.length === 1
      ? topGenres[0].toLowerCase()
      : "";

  const hasReddit = sources.has("reddit_pairs") || sources.has("multi_signal");
  const hasSemantic = sources.has("semantic_fallback");
  const hasTmdb = sources.has("tmdb_recs") || sources.has("multi_signal");

  let intro = `Looking for series similar to ${anchorTitle}? These recommendations highlight shows that viewers often move to next after finishing it.`;

  if (genreText && hasReddit && hasTmdb) {
    intro = `Looking for shows like ${anchorTitle}? This list focuses on ${genreText} series that line up well with ${anchorTitle}, combining audience viewing patterns with closely related recommendation signals.`;
  } else if (genreText && hasReddit) {
    intro = `Looking for shows like ${anchorTitle}? These picks lean into the ${genreText} elements that often connect with fans of ${anchorTitle}.`;
  } else if (genreText && hasSemantic) {
    intro = `Looking for shows like ${anchorTitle}? These recommendations were chosen for their shared ${genreText} appeal, with a similar tone, style or storytelling feel.`;
  } else if (topText) {
    intro = `Looking for shows like ${anchorTitle}? Start with ${topText} — they’re among the strongest next-watch options for fans of ${anchorTitle}.`;
  }

  let seo = `If you enjoyed ${anchorTitle}, these recommendations point you toward similar TV series with overlapping tone, storytelling style and audience appeal.`;

  if (topText && genreText) {
    seo = `If you enjoyed ${anchorTitle}, you may also like ${topText}. These recommendations reflect the kind of ${genreText} storytelling that often appeals to viewers looking for something with a similar feel.`;
  } else if (topText) {
    seo = `If you enjoyed ${anchorTitle}, you may also like ${topText}. These shows were selected because they offer a similar viewing experience for fans looking for what to watch next.`;
  }

  return { intro, seo };
}

function buildFaq(anchorTitle: string, recs: SeoRec[]) {
  const top3 = toTitleList(recs, 3);
  const topText = joinNatural(top3);

  const allGenres = recs.flatMap((r) => r.genres || []);
  const genreCounts = new Map<string, number>();

  for (const genre of allGenres) {
    const g = String(genre || "").trim();
    if (!g) continue;
    genreCounts.set(g, (genreCounts.get(g) || 0) + 1);
  }

  const topGenres = [...genreCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2)
    .map(([g]) => g);

  const genreText =
    topGenres.length === 2
      ? `${topGenres[0].toLowerCase()} and ${topGenres[1].toLowerCase()}`
      : topGenres.length === 1
      ? topGenres[0].toLowerCase()
      : "character-driven";

  return [
    {
      q: `Why do people who like ${anchorTitle} enjoy these shows?`,
      a: topText
        ? `${anchorTitle} tends to appeal to viewers who enjoy strong tone, memorable characters and a story that keeps building over time. Shows like ${topText} offer a similar kind of pull, even when they take that idea in slightly different directions.`
        : `${anchorTitle} tends to attract viewers who enjoy strong storytelling, distinctive tone and character-led plots.`,
    },
    {
      q: `What should I watch after ${anchorTitle}?`,
      a: topText
        ? `A good next watch after ${anchorTitle} depends on what you liked most about it. ${topText} are all strong follow-up options, whether you were drawn in by the atmosphere, the characters or the pacing.`
        : `Your next watch after ${anchorTitle} really depends on whether you liked its tone, pacing or character work most.`,
    },
    {
      q: `What kind of shows are usually recommended to fans of ${anchorTitle}?`,
      a: `Fans of ${anchorTitle} are often recommended ${genreText} series with a similar balance of tension, character focus and story momentum rather than shows that only match on genre alone.`,
    },
    {
      q: `Where can I discover more shows like ${anchorTitle}?`,
      a: `WhatNext helps you discover more shows based on your taste. Save favourites, build a watchlist and rate what you’ve seen to keep improving your recommendations over time.`,
    },
  ];
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
    let cancelled = false;

    async function loadUserLists() {
      if (!userId) {
        setFavSet(new Set());
        setWatchSet(new Set());
        return;
      }

      try {
        const [favRes, watchRes] = await Promise.all([
          fetch(apiUrl(`/users/${userId}/favorites`), { headers }),
          fetch(apiUrl(`/library/${userId}/watchlist`), { headers }),
        ]);

        if (cancelled) return;

        if (favRes.ok) {
          const favs = await favRes.json();
          const favIds = new Set<number>(
            (Array.isArray(favs) ? favs : [])
              .map((x: any) => Number(x?.show_id ?? x?.tmdb_id ?? x?.external_id))
              .filter((n: number) => Number.isFinite(n) && n > 0)
          );
          setFavSet(favIds);
        } else {
          setFavSet(new Set());
        }

        if (watchRes.ok) {
          const watch = await watchRes.json();
          const watchIds = new Set<number>(
            (Array.isArray(watch) ? watch : [])
              .map((x: any) => Number(x?.show_id ?? x?.tmdb_id ?? x?.external_id))
              .filter((n: number) => Number.isFinite(n) && n > 0)
          );
          setWatchSet(watchIds);
        } else {
          setWatchSet(new Set());
        }
      } catch {
        if (!cancelled) {
          setFavSet(new Set());
          setWatchSet(new Set());
        }
      }
    }

    void loadUserLists();

    return () => {
      cancelled = true;
    };
  }, [userId, headers]);

  const relatedPages = useMemo(() => {
    return recs
      .filter((r) => r?.title)
      .slice(0, 6)
      .map((r) => ({
        title: r.title,
        slug: slugifyTitle(r.title),
      }));
  }, [recs]);

  const topTitles = useMemo(() => joinNatural(toTitleList(recs, 3)), [recs]);
  const heroCopy = useMemo(() => {
    if (!anchor?.title) return { intro: "", seo: "" };
    return buildIntro(anchor.title, recs);
  }, [anchor, recs]);

  const faqItems = useMemo(() => {
    if (!anchor?.title) return [];
    return buildFaq(anchor.title, recs);
  }, [anchor, recs]);

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
    if (!anchor?.title || faqItems.length === 0) return;

    const faqSchema = {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: faqItems.map((item) => ({
        "@type": "Question",
        name: item.q,
        acceptedAnswer: {
          "@type": "Answer",
          text: item.a,
        },
      })),
    };

    const existing = document.getElementById("shows-like-faq-schema");
    if (existing) existing.remove();

    const script = document.createElement("script");
    script.id = "shows-like-faq-schema";
    script.type = "application/ld+json";
    script.text = JSON.stringify(faqSchema);
    document.head.appendChild(script);
  }, [anchor, faqItems]);

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

        <p className="shows-like-intro">{heroCopy.intro}</p>

        {heroCopy.seo && (
          <p className="shows-like-seo">{heroCopy.seo}</p>
        )}
      </div>

      <div className="tile-grid">
        {recs.map((r) => (
          <ShowCard
            key={r.tmdb_id}
            show={r}
            isFavorite={favSet.has(r.tmdb_id)}
            isWatchlist={watchSet.has(r.tmdb_id)}
          />
        ))}
      </div>

      <section className="shows-like-faq">
        <h2 className="shows-like-faq__title">Frequently asked questions</h2>

        {faqItems.map((item, i) => (
          <div key={i} className="shows-like-faq__item">
            <h3>{item.q}</h3>
            <p>{item.a}</p>
          </div>
        ))}
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
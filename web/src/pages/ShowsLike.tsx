import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiUrl } from "../api";
import { useAuth } from "../auth/AuthProvider";
import SeoRecommendationCard, { SeoRecommendation } from "../components/SeoRecommendationCard";
import "./ShowsLikeV2.css";
import "./ShowsLike_conversion.css";

type SeoAnchor = {
  tmdb_id: number;
  title: string;
  poster_path?: string | null;
};

type PageCopy = {
  intro?: string;
  seo_blurb?: string;
  top_titles_text?: string;
  top_genres?: string[];
  audience_profile?: {
    headline?: string;
    themes?: string[];
    mood?: string;
    storytelling_angle?: string;
    hook?: string;
    summary?: string;
  };
  content_sections?: Array<{
    heading?: string;
    body?: string;
    bullets?: string[];
  }>;
  best_for?: Array<{
    title?: string;
    match_percent?: number;
    best_for?: string;
    why?: string;
  }>;
  related_page_links?: Array<{
    title?: string;
    href?: string;
  }>;
  faq_items?: Array<{
    question?: string;
    answer?: string;
    q?: string;
    a?: string;
  }>;
};

type SeoResponse = {
  anchor?: SeoAnchor | null;
  recommendations?: SeoRecommendation[];
  page_copy?: PageCopy;
};

const TMDB_IMG = "https://image.tmdb.org/t/p/w500";
const FALLBACK_FEATURED_LINKS = [
  "Breaking Bad",
  "Better Call Saul",
  "Dark",
  "Silo",
  "Severance",
  "The Wire",
  "Fargo",
  "Succession",
  "True Detective",
  "The Expanse",
];

function slugifyTitle(title: string): string {
  return String(title || "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function getPosterUrl(anchor: SeoAnchor | null): string | null {
  const path = anchor?.poster_path;
  if (!path) return null;
  if (path.startsWith("http")) return path;
  return `${TMDB_IMG}${path}`;
}

function getAuthHeaders(): Record<string, string> {
  const h: Record<string, string> = {};
  const token = window.localStorage.getItem("access_token");
  if (token) h.Authorization = `Bearer ${token}`;
  return h;
}

function joinNatural(items: string[]): string {
  const clean = items.map((x) => String(x || "").trim()).filter(Boolean);
  if (clean.length === 0) return "";
  if (clean.length === 1) return clean[0];
  if (clean.length === 2) return `${clean[0]} and ${clean[1]}`;
  return `${clean.slice(0, -1).join(", ")}, and ${clean[clean.length - 1]}`;
}

function topTitles(recs: SeoRecommendation[], max = 3): string[] {
  return recs.slice(0, max).map((r) => r.title).filter(Boolean);
}

function genreSummary(recs: SeoRecommendation[]): string[] {
  const counts = new Map<string, number>();
  for (const rec of recs) {
    const genres = Array.isArray(rec.genres) ? rec.genres : Array.isArray(rec.genre_names) ? rec.genre_names : [];
    for (const g of genres) {
      const clean = String(g || "").trim();
      if (clean) counts.set(clean, (counts.get(clean) || 0) + 1);
    }
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([g]) => g);
}

function buildFallbackIntro(anchorTitle: string, recs: SeoRecommendation[]): string {
  const titles = joinNatural(topTitles(recs, 3));
  if (titles) {
    return `Looking for shows like ${anchorTitle}? Start with ${titles}. These picks are chosen to match the tone, story shape and viewing appeal that fans often want after finishing ${anchorTitle}.`;
  }
  return `Looking for shows like ${anchorTitle}? This page highlights TV series with similar tone, story shape, audience appeal and recommendation signals.`;
}

function buildFallbackFaq(anchorTitle: string, recs: SeoRecommendation[]) {
  const titles = joinNatural(topTitles(recs, 3));
  const genres = joinNatural(genreSummary(recs).slice(0, 2).map((g) => g.toLowerCase()));
  return [
    {
      question: `What should I watch after ${anchorTitle}?`,
      answer: titles
        ? `Start with ${titles}. They are the strongest follow-up options on this page because they combine similarity, quality and audience recommendation signals.`
        : `The best follow-up depends on whether you want a similar mood, story structure, characters or genre.`
    },
    {
      question: `Why are these shows similar to ${anchorTitle}?`,
      answer: `WhatNext compares more than broad genre labels. It looks for overlap in story themes, tone, audience behaviour, recommendation graph signals and quality indicators.`
    },
    {
      question: `Are these just ${genres || "same-genre"} recommendations?`,
      answer: `No. Genre is only one signal. The list is designed to avoid lazy matches and prioritise shows that feel right for fans of ${anchorTitle}.`
    },
    {
      question: `How can I get more personalised recommendations?`,
      answer: `Save favourites, build a watchlist and rate shows you have watched. WhatNext can then tune recommendations around your own taste instead of a single title.`
    },
  ];
}

function safeText(value: unknown): string {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function schemaScript(id: string, data: unknown) {
  const existing = document.getElementById(id);
  if (existing) existing.remove();

  const script = document.createElement("script");
  script.id = id;
  script.type = "application/ld+json";
  script.text = JSON.stringify(data);
  document.head.appendChild(script);
}

function removeSchema(id: string) {
  const existing = document.getElementById(id);
  if (existing) existing.remove();
}

export default function ShowsLike() {
  const { slug } = useParams();
  const { user } = useAuth();
  const userId = user?.id ?? null;

  const [anchor, setAnchor] = useState<SeoAnchor | null>(null);
  const [recs, setRecs] = useState<SeoRecommendation[]>([]);
  const [pageCopy, setPageCopy] = useState<PageCopy | null>(null);
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

        const response = await fetch(apiUrl(`/seo/shows-like/${slug}`));
        if (!response.ok) throw new Error(`Failed to load page (${response.status})`);

        const data: SeoResponse = await response.json();
        if (cancelled) return;

        setAnchor(data.anchor ?? null);
        setRecs(Array.isArray(data.recommendations) ? data.recommendations : []);
        setPageCopy(data.page_copy ?? null);
      } catch (err: any) {
        if (!cancelled) setError(err?.message || "Failed to load recommendations.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    if (slug) void load();

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
          setFavSet(new Set((Array.isArray(favs) ? favs : [])
            .map((x: any) => Number(x?.show_id ?? x?.tmdb_id ?? x?.external_id))
            .filter((n: number) => Number.isFinite(n) && n > 0)));
        }

        if (watchRes.ok) {
          const watch = await watchRes.json();
          setWatchSet(new Set((Array.isArray(watch) ? watch : [])
            .map((x: any) => Number(x?.show_id ?? x?.tmdb_id ?? x?.external_id))
            .filter((n: number) => Number.isFinite(n) && n > 0)));
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

  const anchorTitle = anchor?.title || "this show";
  const anchorPoster = useMemo(() => getPosterUrl(anchor), [anchor]);
  const featuredRecs = useMemo(() => recs.slice(0, 6), [recs]);
  const moreRecs = useMemo(() => recs.slice(6), [recs]);
  const topThreeText = useMemo(() => pageCopy?.top_titles_text || joinNatural(topTitles(recs, 3)), [pageCopy, recs]);
  const topGenres = useMemo(() => pageCopy?.top_genres?.length ? pageCopy.top_genres : genreSummary(recs), [pageCopy, recs]);
  const faqItems = useMemo(() => {
    const fromApi = pageCopy?.faq_items || [];
    if (fromApi.length > 0) {
      return fromApi.map((x) => ({
        question: safeText(x.question || x.q),
        answer: safeText(x.answer || x.a),
      })).filter((x) => x.question && x.answer);
    }
    return buildFallbackFaq(anchorTitle, recs);
  }, [pageCopy, anchorTitle, recs]);

  const relatedLinks = useMemo(() => {
    const fromApi = (pageCopy?.related_page_links || [])
      .map((x) => ({ title: safeText(x.title), href: safeText(x.href) }))
      .filter((x) => x.title && x.href)
      .slice(0, 12);

    if (fromApi.length > 0) return fromApi;

    return recs.slice(0, 12).map((r) => ({
      title: `Shows like ${r.title}`,
      href: `/shows-like/${slugifyTitle(r.title)}`,
    }));
  }, [pageCopy, recs]);

  const popularLinks = useMemo(() => {
    const combined = [...relatedLinks.map((x) => x.title.replace(/^Shows like\s+/i, "")), ...FALLBACK_FEATURED_LINKS];
    const seen = new Set<string>();
    return combined
      .filter((title) => {
        const clean = safeText(title);
        const key = clean.toLowerCase();
        if (!clean || key === anchorTitle.toLowerCase() || seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, 10);
  }, [relatedLinks, anchorTitle]);

  useEffect(() => {
    if (!anchor?.title || !slug) return;

    const title = `Shows Like ${anchor.title}: What to Watch Next | WhatNextTV`;
    const description = pageCopy?.seo_blurb
      ? safeText(pageCopy.seo_blurb).slice(0, 158)
      : `Looking for shows like ${anchor.title}? Discover similar TV series with match reasons, quality signals and recommendations from WhatNextTV.`;

    document.title = title;

    let meta = document.querySelector('meta[name="description"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "description");
      document.head.appendChild(meta);
    }
    meta.setAttribute("content", description);

    let canonical = document.querySelector('link[rel="canonical"]');
    if (!canonical) {
      canonical = document.createElement("link");
      canonical.setAttribute("rel", "canonical");
      document.head.appendChild(canonical);
    }
    canonical.setAttribute("href", `${window.location.origin}/shows-like/${slug}`);
  }, [anchor, slug, pageCopy]);

  useEffect(() => {
    if (!anchor?.title || recs.length === 0 || !slug) {
      removeSchema("shows-like-rich-schema");
      return;
    }

    const url = `${window.location.origin}/shows-like/${slug}`;
    const itemList = {
      "@context": "https://schema.org",
      "@type": "ItemList",
      name: `Shows like ${anchor.title}`,
      description: pageCopy?.seo_blurb || `TV recommendations similar to ${anchor.title}.`,
      url,
      itemListElement: recs.slice(0, 12).map((rec, index) => ({
        "@type": "ListItem",
        position: index + 1,
        item: {
          "@type": "TVSeries",
          name: rec.title,
          url: `${window.location.origin}/show/${rec.tmdb_id}`,
          aggregateRating: rec.vote_average ? {
            "@type": "AggregateRating",
            ratingValue: Number(rec.vote_average).toFixed(1),
            bestRating: "10",
            ratingCount: rec.vote_count || undefined,
          } : undefined,
        },
      })),
    };

    const faqSchema = {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: faqItems.map((item) => ({
        "@type": "Question",
        name: item.question,
        acceptedAnswer: {
          "@type": "Answer",
          text: item.answer,
        },
      })),
    };

    const breadcrumb = {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "Home", item: window.location.origin },
        { "@type": "ListItem", position: 2, name: "Shows Like", item: `${window.location.origin}/shows-like` },
        { "@type": "ListItem", position: 3, name: `Shows Like ${anchor.title}`, item: url },
      ],
    };

    const webPage = {
      "@context": "https://schema.org",
      "@type": "WebPage",
      name: `Shows Like ${anchor.title}`,
      description: pageCopy?.seo_blurb || `Find TV shows similar to ${anchor.title}.`,
      url,
      mainEntity: itemList,
    };

    schemaScript("shows-like-rich-schema", [webPage, breadcrumb, itemList, faqSchema]);
  }, [anchor, slug, recs, faqItems, pageCopy]);

  if (!slug) {
    return (
      <div className="page-body shows-like-v2-page">
        <div className="glass-card admin-empty">Invalid page.</div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="page-body shows-like-v2-page">
        <div className="glass-card admin-empty">Loading richer recommendations…</div>
      </div>
    );
  }

  if (error || !anchor) {
    return (
      <div className="page-body shows-like-v2-page">
        <div className="glass-card admin-empty">{error || "We couldn't find that show."}</div>
      </div>
    );
  }

  return (
    <div className="page-body shows-like-v2-page">
      <nav className="shows-like-v2-breadcrumb" aria-label="Breadcrumb">
        <Link to="/">Home</Link>
        <span>›</span>
        <Link to="/shows-like">Shows Like</Link>
        <span>›</span>
        <span>{anchor.title}</span>
      </nav>

      <section className="shows-like-v2-hero glass-card-glow">
        <div className="shows-like-v2-hero__copy">
          <div className="shows-like-v2-eyebrow">What to watch next</div>
          <h1>Shows Like {anchor.title}</h1>
          <p className="shows-like-v2-lede">
            {pageCopy?.intro || buildFallbackIntro(anchor.title, recs)}
          </p>
          {pageCopy?.seo_blurb && <p className="shows-like-v2-sublede">{pageCopy.seo_blurb}</p>}

          <div className="shows-like-v2-hero__actions">
            <a href="#recommendations" className="glass-button-primary">See the matches</a>
            <Link to="/search" className="glass-button">Search another show</Link>
          </div>

          <div className="shows-like-v2-stats" aria-label="Page summary">
            <span><strong>{recs.length}</strong> recommendations</span>
            {topThreeText && <span><strong>Start with</strong> {topThreeText}</span>}
            {topGenres.slice(0, 2).length > 0 && <span><strong>Key genres</strong> {joinNatural(topGenres.slice(0, 2))}</span>}
          </div>
        </div>

        <div className="shows-like-v2-hero__poster-area">
          {anchorPoster ? (
            <img src={anchorPoster} alt={`${anchor.title} poster`} className="shows-like-v2-hero__poster" />
          ) : (
            <div className="shows-like-v2-hero__poster shows-like-v2-hero__poster--empty">{anchor.title}</div>
          )}
          <div className="shows-like-v2-hero__poster-caption">
            Recommendations tuned for fans of <strong>{anchor.title}</strong>
          </div>
        </div>
      </section>

      {pageCopy?.audience_profile && (
        <section className="shows-like-v2-section shows-like-v2-audience glass-card">
          <div>
            <p className="shows-like-v2-section-label">Audience fit</p>
            <h2>{pageCopy.audience_profile.headline || `Why ${anchor.title} fans may like these shows`}</h2>
            <p>{pageCopy.audience_profile.summary}</p>
          </div>
          <div className="shows-like-v2-audience__chips">
            {(pageCopy.audience_profile.themes || []).map((theme) => <span key={theme}>{theme}</span>)}
            {pageCopy.audience_profile.mood && <span>{pageCopy.audience_profile.mood} mood</span>}
            {pageCopy.audience_profile.storytelling_angle && <span>{pageCopy.audience_profile.storytelling_angle}</span>}
          </div>
        </section>
      )}

      <section id="recommendations" className="shows-like-v2-section">
        <div className="shows-like-v2-section__header">
          <p className="shows-like-v2-section-label">Ranked recommendations</p>
          <h2>The closest TV shows to watch after {anchor.title}</h2>
          <p>
            Each recommendation includes a match score and the visible reasoning behind the pick, so this page is useful for viewers and easier for search engines to understand.
          </p>
        </div>

        <div className="shows-like-v2-rec-list">
          {featuredRecs.map((rec) => (
            <SeoRecommendationCard
              key={rec.tmdb_id}
              anchorTitle={anchor.title}
              rec={rec}
              isFavorite={favSet.has(rec.tmdb_id)}
              isWatchlist={watchSet.has(rec.tmdb_id)}
            />
          ))}
        </div>
      </section>

      <section className="shows-like-v2-conversion glass-card-glow" aria-label="Personalised recommendations">
        <div className="shows-like-v2-conversion__copy">
          <p className="shows-like-v2-section-label">Make WhatNext personal</p>
          <h2>One show gave you these recommendations. Your whole taste can give you better ones.</h2>
          <p>{user ? "Add more favourites and rate shows you have watched so WhatNext can keep improving the recommendations built around your taste." : "Create a free account, add your favourite shows and rate what you have watched. WhatNext can then recommend TV based on your combined taste instead of a single title."}</p>
          <div className="shows-like-v2-conversion__benefits">
            <span>✓ Build a taste profile</span><span>✓ Rate shows you have watched</span>
            <span>✓ Save favourites and a watchlist</span><span>✓ Get personalised recommendations</span>
          </div>
        </div>
        <div className="shows-like-v2-conversion__actions">
          {user ? (<><Link to="/search" className="glass-button-primary">Add favourites and ratings</Link><Link to="/recommendations" className="glass-button">View my recommendations</Link></>) : (<><Link to="/register" className="glass-button-primary">Build my TV taste profile</Link><span className="shows-like-v2-conversion__note">Free account · Personalises as you rate more TV</span></>)}
        </div>
      </section>

      {pageCopy?.best_for && pageCopy.best_for.length > 0 && (
        <section className="shows-like-v2-section shows-like-v2-table-section glass-card">
          <div className="shows-like-v2-section__header">
            <p className="shows-like-v2-section-label">Quick comparison</p>
            <h2>Which {anchor.title} follow-up should you choose?</h2>
          </div>
          <div className="shows-like-v2-table-wrap">
            <table className="shows-like-v2-table">
              <thead>
                <tr>
                  <th>Show</th>
                  <th>Match</th>
                  <th>Best for</th>
                </tr>
              </thead>
              <tbody>
                {pageCopy.best_for.slice(0, 8).map((item) => (
                  <tr key={item.title}>
                    <td>{item.title}</td>
                    <td>{item.match_percent ? `${item.match_percent}%` : "Strong"}</td>
                    <td>{item.best_for}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {moreRecs.length > 0 && (
        <section className="shows-like-v2-section">
          <div className="shows-like-v2-section__header">
            <p className="shows-like-v2-section-label">More options</p>
            <h2>More shows that may suit {anchor.title} fans</h2>
          </div>
          <div className="shows-like-v2-compact-grid">
            {moreRecs.map((rec) => (
              <SeoRecommendationCard
                key={rec.tmdb_id}
                anchorTitle={anchor.title}
                rec={rec}
                variant="compact"
                isFavorite={favSet.has(rec.tmdb_id)}
                isWatchlist={watchSet.has(rec.tmdb_id)}
              />
            ))}
          </div>
        </section>
      )}

      {pageCopy?.content_sections && pageCopy.content_sections.length > 0 && (
        <section className="shows-like-v2-section shows-like-v2-explainers">
          {pageCopy.content_sections.map((section) => (
            <article key={section.heading} className="shows-like-v2-explainer glass-card">
              <h2>{section.heading}</h2>
              {section.body && <p>{section.body}</p>}
              {Array.isArray(section.bullets) && section.bullets.length > 0 && (
                <ul>
                  {section.bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}
                </ul>
              )}
            </article>
          ))}
        </section>
      )}

      <section className="shows-like-v2-section shows-like-v2-faq glass-card">
        <div className="shows-like-v2-section__header">
          <p className="shows-like-v2-section-label">FAQ</p>
          <h2>Questions about shows like {anchor.title}</h2>
        </div>
        <div className="shows-like-v2-faq__items">
          {faqItems.map((item) => (
            <article key={item.question} className="shows-like-v2-faq__item">
              <h3>{item.question}</h3>
              <p>{item.answer}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="shows-like-v2-section shows-like-v2-related glass-card">
        <div className="shows-like-v2-section__header">
          <p className="shows-like-v2-section-label">Internal discovery</p>
          <h2>Explore related recommendation pages</h2>
          <p>These links help viewers keep browsing and help search engines discover more of WhatNextTV naturally.</p>
        </div>
        <div className="shows-like-v2-related__links">
          {relatedLinks.map((item) => (
            <Link key={`${item.href}-${item.title}`} to={item.href}>{item.title}</Link>
          ))}
        </div>
      </section>

      <section className="shows-like-v2-section shows-like-v2-popular">
        <div className="shows-like-v2-section__header">
          <p className="shows-like-v2-section-label">Popular searches</p>
          <h2>More shows people search for</h2>
        </div>
        <div className="shows-like-v2-popular__links">
          {popularLinks.map((title) => (
            <Link key={title} to={`/shows-like/${slugifyTitle(title)}`}>Shows like {title}</Link>
          ))}
        </div>
      </section>

      <section className="shows-like-v2-cta glass-card-glow">
        <h2>Want recommendations tuned to your own taste?</h2>
        <p>Search a favourite show, save what you like, build your watchlist and let WhatNextTV learn what actually works for you.</p>
        <div className="shows-like-v2-hero__actions">
          <Link to="/search" className="glass-button-primary">Search a show</Link>
          <Link to="/discover" className="glass-button">Browse Discover</Link>
        </div>
      </section>
    </div>
  );
}

import React, { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import ShowCard from "../components/ShowCard";
import "./Homepage.css";

type Show = {
  tmdb_id?: number;
  show_id?: number;
  external_id?: number;
  id?: number;
  title?: string;
  name?: string;
  poster_path?: string | null;
  poster_url?: string | null;
  overview?: string | null;
  vote_average?: number;
  vote_count?: number;
  genre_names?: string[];
  first_air_date?: string;
  [key: string]: any;
};

type DiscoverResponse = {
  featured?: Show[];
  trending?: Show[];
  top_decade?: Show[];
  genres?: Record<string, Show[]>;
};

type TopRatedShow = Show & {
  avg_rating?: number;
  ratings_count?: number;
  weighted_score?: number;
};

type ShowsLikeLink = {
  slug: string;
  title: string;
  hook: string;
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

const popularShowsLike: ShowsLikeLink[] = [
  { slug: "breaking-bad", title: "Breaking Bad", hook: "crime, antiheroes and pressure-cooker drama" },
  { slug: "dark", title: "Dark", hook: "time loops, mystery and big sci-fi payoff" },
  { slug: "silo", title: "Silo", hook: "contained dystopia and slow-burn secrets" },
  { slug: "severance", title: "Severance", hook: "corporate mystery and psychological sci-fi" },
  { slug: "the-wire", title: "The Wire", hook: "prestige crime drama and social realism" },
  { slug: "succession", title: "Succession", hook: "power, money and family rivalry" },
  { slug: "true-detective", title: "True Detective", hook: "dark investigations and atmospheric mystery" },
  { slug: "the-expanse", title: "The Expanse", hook: "space politics and epic sci-fi world-building" },
];

const recommendationSignals = [
  "Story themes",
  "Character types",
  "Tone and mood",
  "Pacing",
  "Audience ratings",
  "Reddit recommendations",
  "Viewing patterns",
  "Hidden-gem potential",
];

const quickSearches = ["Breaking Bad", "Dark", "Silo", "Severance", "The Bear", "The Wire"];

const featureCards = [
  {
    title: "Find shows like your favourites",
    desc: "Search a series you already love and jump into similar TV shows, ranked by fit rather than genre alone.",
    to: "/shows-like",
  },
  {
    title: "Explore trending TV shows",
    desc: "Browse current, popular and talked-about series when you want something new but do not know where to start.",
    to: "/discover",
  },
  {
    title: "Browse top rated shows",
    desc: "See the highest rated series from WhatNext users and use the list as a shortcut to quality TV.",
    to: "/top-rated",
  },
];

export default function Homepage() {
  const navigate = useNavigate();
  const [searchTerm, setSearchTerm] = useState("");
  const [trending, setTrending] = useState<Show[]>([]);
  const [featured, setFeatured] = useState<Show[]>([]);
  const [topRated, setTopRated] = useState<TopRatedShow[]>([]);
  const [loading, setLoading] = useState(true);
  const [topRatedLoading, setTopRatedLoading] = useState(true);

  useEffect(() => {
    let alive = true;

    const load = async () => {
      try {
        const res = await fetch("/api/discover");
        if (!res.ok) throw new Error(String(res.status));
        const data: DiscoverResponse = await res.json();
        if (!alive) return;
        setTrending(Array.isArray(data.trending) ? data.trending.slice(0, 8) : []);
        setFeatured(Array.isArray(data.featured) ? data.featured.slice(0, 6) : []);
      } catch {
        if (!alive) return;
        setTrending([]);
        setFeatured([]);
      } finally {
        if (alive) setLoading(false);
      }
    };

    void load();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;

    const loadTopRated = async () => {
      try {
        const res = await fetch("/api/shows/top-rated?limit=5&min_votes=2");
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        if (!alive) return;
        setTopRated(Array.isArray(data) ? data : []);
      } catch {
        if (!alive) return;
        setTopRated([]);
      } finally {
        if (alive) setTopRatedLoading(false);
      }
    };

    void loadTopRated();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    document.title = "WhatNextTV | Find TV Shows Like Your Favourites";

    let meta = document.querySelector('meta[name="description"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "description");
      document.head.appendChild(meta);
    }
    meta.setAttribute(
      "content",
      "Find what to watch next with personalised TV recommendations, shows-like pages, Reddit community signals, ratings, watchlists and similarity matching."
    );

    const jsonLdId = "whatnext-homepage-jsonld";
    const existing = document.getElementById(jsonLdId);
    if (existing) existing.remove();

    const script = document.createElement("script");
    script.id = jsonLdId;
    script.type = "application/ld+json";
    script.text = JSON.stringify({
      "@context": "https://schema.org",
      "@type": "WebSite",
      name: "WhatNextTV",
      url: "https://whatnexttv.org/",
      description:
        "A TV recommendation website for finding shows similar to the series you already love.",
      potentialAction: {
        "@type": "SearchAction",
        target: "https://whatnexttv.org/search?q={search_term_string}",
        "query-input": "required name=search_term_string",
      },
    });
    document.head.appendChild(script);

    return () => {
      const current = document.getElementById(jsonLdId);
      if (current) current.remove();
    };
  }, []);

  const heroTrendingText = useMemo(() => {
    const names = trending
      .slice(0, 4)
      .map((s) => s.title || s.name)
      .filter(Boolean);
    return names.join(" • ");
  }, [trending]);

  const handleSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const q = searchTerm.trim();
    if (!q) {
      navigate("/search");
      return;
    }
    navigate(`/shows-like/${slugifyTitle(q)}`);
  };

  return (
    <div className="homepage-shell">
      <section className="homepage-hero glass-card-glow">
        <div className="homepage-hero__content">
          <div className="homepage-hero__eyebrow">WhatNextTV</div>
          <h1 className="homepage-hero__title">Never wonder what to watch next again.</h1>
          <p className="homepage-hero__subtitle">
            Find TV shows you will actually love using personalised recommendations,
            Reddit community signals and intelligent similarity matching — not just broad genre labels.
          </p>

          <form onSubmit={handleSearch} style={{ marginTop: 24, maxWidth: 720 }}>
            <label htmlFor="homepage-show-search" style={{ display: "block", marginBottom: 8, fontWeight: 700 }}>
              What TV show did you just finish?
            </label>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <input
                id="homepage-show-search"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Try Breaking Bad, Dark, Silo or Severance"
                style={{
                  flex: "1 1 320px",
                  minHeight: 48,
                  borderRadius: 14,
                  border: "1px solid rgba(255,255,255,0.2)",
                  padding: "0 16px",
                  fontSize: 16,
                }}
              />
              <button type="submit" className="glass-button-primary" style={{ minHeight: 48 }}>
                Find Recommendations
              </button>
            </div>
          </form>

          <div className="homepage-hero__meta" style={{ marginTop: 18 }}>
            {quickSearches.map((name) => (
              <button
                key={name}
                type="button"
                className="homepage-chip"
                onClick={() => navigate(`/shows-like/${slugifyTitle(name)}`)}
                style={{ cursor: "pointer" }}
              >
                {name}
              </button>
            ))}
          </div>

          <div className="homepage-hero__actions" style={{ marginTop: 22 }}>
            <Link to="/shows-like" className="glass-button-primary">
              Browse Shows Like Pages
            </Link>
            <Link to="/discover" className="glass-button">
              Explore Trending TV
            </Link>
          </div>

          {heroTrendingText && (
            <p className="homepage-hero__trending">
              <strong>Trending on WhatNext:</strong> {heroTrendingText}
            </p>
          )}
        </div>

        <div className="homepage-hero__logo-wrap">
          <div className="homepage-hero__logo-glow" />
          <img src="/logo1.png" alt="WhatNextTV logo" className="homepage-hero__logo" />
        </div>
      </section>

      <section className="homepage-section">
        <div className="homepage-section__header">
          <h2 className="homepage-section__title">Popular Shows Like pages</h2>
          <p className="homepage-section__copy">
            Start with high-intent recommendation pages for the shows people most often search for after finishing a great series.
          </p>
        </div>

        <div className="homepage-showslike-compact-grid">
          {popularShowsLike.map((item) => (
            <Link
              key={item.slug}
              to={`/shows-like/${item.slug}`}
              className="homepage-showslike-compact-link"
            >
              Shows like {item.title}
            </Link>
          ))}
            <Link to="/seo-index" className="glass-button">
            Browse all recommendation pages
            </Link>
        </div>

        
      </section>

      <section className="homepage-section glass-card" style={{ padding: 24 }}>
        <div className="homepage-section__header">
          <h2 className="homepage-section__title">Why WhatNext recommendations are different</h2>
          <p className="homepage-section__copy">
            Most recommendation sites stop at genre. WhatNext looks for the deeper reasons you liked a show: the story shape, the characters, the atmosphere, the pacing and what real viewers recommend next.
          </p>
        </div>

        <div className="homepage-grid">
          {recommendationSignals.map((signal) => (
            <div key={signal} className="homepage-feature-card">
              <div className="homepage-feature-card__emoji">✓</div>
              <h3 className="homepage-feature-card__title">{signal}</h3>
              <p className="homepage-feature-card__desc">
                Used as part of the matching process so recommendations feel closer to your actual taste.
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="homepage-section">
        <div className="homepage-section__header">
          <h2 className="homepage-section__title">How WhatNext helps you choose faster</h2>
          <p className="homepage-section__copy">
            Search a favourite show, compare similar series, save what looks good and build a watchlist that improves as you rate more TV.
          </p>
        </div>

        <div className="homepage-grid">
          {featureCards.map((item) => (
            <Link key={item.title} to={item.to} className="homepage-feature-card glass-card">
              <h3 className="homepage-feature-card__title">{item.title}</h3>
              <p className="homepage-feature-card__desc">{item.desc}</p>
              <span className="homepage-feature-card__cta">Open section →</span>
            </Link>
          ))}
        </div>
      </section>

      <section className="homepage-section">
        <div className="homepage-section__header">
          <h2 className="homepage-section__title">Trending now on WhatNext</h2>
          <p className="homepage-section__copy">
            Fresh titles from the Discover feed for when you want something current, popular or newly talked about.
          </p>
        </div>

        {loading ? (
          <div className="glass-card admin-empty">Loading trending shows…</div>
        ) : trending.length > 0 ? (
          <div className="tile-grid">
            {trending.map((show) => {
              const tmdbId = getTmdbId(show);
              return tmdbId ? <ShowCard key={tmdbId} show={show} /> : null;
            })}
          </div>
        ) : (
          <div className="glass-card admin-empty">Trending shows will appear here once the feed is available.</div>
        )}
      </section>

      <section className="homepage-section">
        <div className="homepage-section__header">
          <h2 className="homepage-section__title">Top rated by WhatNext users</h2>
          <p className="homepage-section__copy">
            Real user ratings from the app, ranked using weighted scores so the list reflects both quality and consistency.
          </p>
        </div>

        {topRatedLoading ? (
          <div className="glass-card admin-empty">Loading top rated shows…</div>
        ) : topRated.length > 0 ? (
          <>
            <div className="tile-grid">
              {topRated.map((show) => {
                const tmdbId = getTmdbId(show);
                return tmdbId ? <ShowCard key={tmdbId} show={show} /> : null;
              })}
            </div>
            <div style={{ marginTop: 16 }}>
              <Link to="/top-rated" className="glass-button-primary">
                View full top rated list
              </Link>
            </div>
          </>
        ) : (
          <div className="glass-card admin-empty">Top rated shows will appear here as more users rate series.</div>
        )}
      </section>

      {featured.length > 0 && (
        <section className="homepage-section">
          <div className="homepage-section__header">
            <h2 className="homepage-section__title">Featured picks</h2>
            <p className="homepage-section__copy">
              A few recommendation-friendly titles from the main Discover feed for a stronger first impression.
            </p>
          </div>

          <div className="tile-grid">
            {featured.map((show) => {
              const tmdbId = getTmdbId(show);
              return tmdbId ? <ShowCard key={tmdbId} show={show} /> : null;
            })}
          </div>
        </section>
      )}

      <section className="homepage-section glass-card" style={{ padding: 24 }}>
        <div className="homepage-section__header">
          <h2 className="homepage-section__title">Find TV shows like the series you already love</h2>
          <p className="homepage-section__copy">
            WhatNext is built for the question people ask after finishing a brilliant show: what should I watch next? Whether you want another crime drama like Breaking Bad, a mystery like Dark, a dystopian sci-fi series like Silo or a power drama like Succession, the aim is to give you recommendations that explain why each show fits.
          </p>
          <p className="homepage-section__copy">
            You can use WhatNext without an account to search and browse recommendations, then register when you want to save favourites, keep a watchlist and make future recommendations more personal.
          </p>
        </div>
      </section>

      <section className="homepage-cta glass-card">
        <h2 className="homepage-cta__title">Ready to find something great?</h2>
        <p className="homepage-cta__copy">
          Search a favourite show, browse similar series and start building your personal TV library.
        </p>
        <div className="homepage-hero__actions">
          <Link to="/search" className="glass-button-primary">
            Search TV Shows
          </Link>
          <Link to="/shows-like" className="glass-button">
            Browse Shows Like Pages
          </Link>
        </div>
      </section>

      <div className="wn-feedback-card">
        <div className="wn-feedback-content">
          <h2>💬 Help Shape WhatNext</h2>
          <p>
            Found a bug? Got an idea? Or just enjoying the app? We are actively improving WhatNext and would love your feedback.
          </p>
          <a href="mailto:whatnexttv@gmail.com?subject=WhatNext Feedback" className="wn-feedback-btn">
            Contact Us
          </a>
        </div>
      </div>
    </div>
  );
}

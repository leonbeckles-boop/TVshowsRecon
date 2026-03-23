import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import ShowCard from "../components/ShowCard";

type Show = {
  tmdb_id?: number;
  show_id?: number;
  external_id?: number;
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

function getTmdbId(x: any): number | null {
  const cand = x?.tmdb_id ?? x?.external_id ?? x?.show_id ?? x?.id;
  const n = Number(cand);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function prettySlug(slug: string): string {
  return slug
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

const featuredShowsLike = [
  "breaking-bad",
  "dark",
  "the-wire",
  "severance",
  "the-boys",
  "succession",
];

const sectionCards = [
  {
    title: "Search",
    emoji: "🔎",
    to: "/search",
    desc: "Search any TV show and jump straight into recommendations, details and similar series.",
  },
  {
    title: "Discover",
    emoji: "🔥",
    to: "/discover",
    desc: "Browse trending and popular shows when you want something new but don’t know where to start.",
  },
  {
    title: "Favourites",
    emoji: "⭐",
    to: "/favorites",
    desc: "Save the shows you love so WhatNext can learn your taste and improve recommendations.",
  },
  {
    title: "Watchlist",
    emoji: "📺",
    to: "/watchlist",
    desc: "Keep track of the series you want to watch next so nothing gets forgotten.",
  },
  {
    title: "Recommendations",
    emoji: "🤖",
    to: "/recs",
    desc: "Get personalised recommendations based on your favourites, watch history and preferences.",
  },
  {
    title: "Profile",
    emoji: "📊",
    to: "/wrapped",
    desc: "See your viewing habits, saved shows and your evolving TV taste profile.",
  },
];

export default function Homepage() {
  const [trending, setTrending] = useState<Show[]>([]);
  const [featured, setFeatured] = useState<Show[]>([]);
  const [loading, setLoading] = useState(true);

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
    document.title = "WhatNextTV | Find Your Next TV Show";
    let meta = document.querySelector('meta[name="description"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "description");
      document.head.appendChild(meta);
    }
    meta.setAttribute(
      "content",
      "Discover what to watch next with personalised TV recommendations, trending shows, favourites, watchlists and shows-like pages."
    );
  }, []);

  const heroTrendingText = useMemo(() => {
    const names = trending
      .slice(0, 4)
      .map((s) => s.title || s.name)
      .filter(Boolean);
    return names.join(" • ");
  }, [trending]);

  return (
    <div className="homepage-shell">
      <section className="homepage-hero glass-card-glow">
        <div className="homepage-hero__content">
          <div className="homepage-hero__eyebrow">WhatNextTV</div>
          <h1 className="homepage-hero__title">Find your next TV show faster.</h1>
          <p className="homepage-hero__subtitle">
            WhatNext helps you discover series similar to the ones you already love,
            track what you’ve watched, save favourites and build a smarter watchlist.
          </p>

          <div className="homepage-hero__actions">
            <Link to="/discover" className="glass-button-primary">
              Start Exploring
            </Link>
            <Link to="/shows-like" className="glass-button">
              Browse “Shows Like” Pages
            </Link>
          </div>

          <div className="homepage-hero__meta">
            <span className="homepage-chip">Recommendations</span>
            <span className="homepage-chip">Watchlist</span>
            <span className="homepage-chip">Favourites</span>
            <span className="homepage-chip">SEO discovery</span>
          </div>

          {heroTrendingText && (
            <p className="homepage-hero__trending">
              <strong>Trending on WhatNext:</strong> {heroTrendingText}
            </p>
          )}
        </div>

        <div className="homepage-hero__logo-wrap">
          <div className="homepage-hero__logo-glow" />
          <img
            src="/logo1.png"
            alt="WhatNextTV logo"
            className="homepage-hero__logo"
          />
        </div>
      </section>

      <section className="homepage-section">
        <div className="homepage-section__header">
          <h2 className="homepage-section__title">Everything in one place</h2>
          <p className="homepage-section__copy">
            Use WhatNext as both a recommendation engine and a simple way to keep
            track of the TV shows you care about.
          </p>
        </div>

        <div className="homepage-grid">
          {sectionCards.map((item) => (
            <Link key={item.title} to={item.to} className="homepage-feature-card glass-card">
              <div className="homepage-feature-card__emoji">{item.emoji}</div>
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
            Fresh titles from your existing Discover feed so the homepage always feels active.
          </p>
        </div>

        {loading ? (
          <div className="glass-card admin-empty">Loading trending shows…</div>
        ) : trending.length > 0 ? (
          <div className="tile-grid">
            {trending.map((show) => {
              const tmdbId = getTmdbId(show);
              return tmdbId ? (
                <ShowCard key={tmdbId} show={show} />
              ) : null;
            })}
          </div>
        ) : (
          <div className="glass-card admin-empty">
            Trending shows will appear here once the feed is available.
          </div>
        )}
      </section>

      <section className="homepage-section">
        <div className="homepage-section__header">
          <h2 className="homepage-section__title">Popular “Shows Like” pages</h2>
          <p className="homepage-section__copy">
            Jump straight into high-intent recommendation pages for some of the most searched shows.
          </p>
        </div>

        <div className="homepage-pill-links">
          {featuredShowsLike.map((slug) => (
            <Link
              key={slug}
              to={`/shows-like/${slug}`}
              className="homepage-pill-link"
            >
              Shows like {prettySlug(slug)}
            </Link>
          ))}
          <Link to="/seo-index" className="homepage-pill-link homepage-pill-link--accent">
            Browse all recommendation pages
          </Link>
        </div>
      </section>

      {featured.length > 0 && (
        <section className="homepage-section">
          <div className="homepage-section__header">
            <h2 className="homepage-section__title">Featured picks</h2>
            <p className="homepage-section__copy">
              A few handoff-friendly titles from your main discover feed for a stronger first impression.
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

      <section className="homepage-cta glass-card">
        <h2 className="homepage-cta__title">Ready to find something great?</h2>
        <p className="homepage-cta__copy">
          Search a favourite show, explore recommendations, and start building your
          personal TV library.
        </p>
        <div className="homepage-hero__actions">
          <Link to="/search" className="glass-button-primary">
            Search Shows
          </Link>
          <Link to="/discover" className="glass-button">
            Explore Discover
          </Link>
        </div>
      </section>

        <div className="wn-feedback-card">
            <div className="wn-feedback-content">
                <h2>💬 Help Shape WhatNext</h2>
                <p>
                Found a bug? Got an idea? Or just enjoying the app?
                We’re actively improving WhatNext and would love your feedback.
                </p>

                <a
                href="mailto:whatnexttv@gmail.com?subject=WhatNext Feedback"
                className="wn-feedback-btn"
                >
                Contact Us
                </a>
            </div>
            </div>
    </div>
  );
}
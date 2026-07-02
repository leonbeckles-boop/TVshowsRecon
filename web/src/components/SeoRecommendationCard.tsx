import React, { useMemo } from "react";
import { Link } from "react-router-dom";
import "./SeoRecommendationCard.css";

export type SeoRecommendation = {
  tmdb_id: number;
  title: string;
  poster_path?: string | null;
  poster_url?: string | null;
  overview?: string | null;
  first_air_date?: string | null;
  genres?: string[];
  genre_names?: string[];
  vote_average?: number | null;
  vote_count?: number | null;
  match_percent?: number | null;
  match_reasons?: string[] | null;
  why_recommended?: string | null;
  source_explanation?: string | null;
  rank?: number | null;
  [key: string]: any;
};

type Props = {
  anchorTitle: string;
  rec: SeoRecommendation;
  variant?: "feature" | "compact";
  isFavorite?: boolean;
  isWatchlist?: boolean;
};

const TMDB_IMG = "https://image.tmdb.org/t/p/w500";

function slugifyTitle(title: string): string {
  return String(title || "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function getPosterUrl(show: SeoRecommendation): string | null {
  const direct = show.poster_url ?? show.posterUrl;
  if (direct && typeof direct === "string") return direct;

  const path = show.poster_path ?? show.details?.poster_path ?? null;
  if (path && typeof path === "string") {
    if (path.startsWith("http")) return path;
    return `${TMDB_IMG}${path}`;
  }

  return null;
}

function getYear(show: SeoRecommendation): string | null {
  const raw = show.first_air_date ?? show.release_date ?? null;
  if (!raw || typeof raw !== "string" || raw.length < 4) return null;
  return raw.slice(0, 4);
}

function getGenres(show: SeoRecommendation): string[] {
  if (Array.isArray(show.genres)) return show.genres.filter(Boolean).slice(0, 4);
  if (Array.isArray(show.genre_names)) return show.genre_names.filter(Boolean).slice(0, 4);
  return [];
}

function cleanReason(reason: string): string {
  return String(reason || "")
    .replace(/^Shared genre fit:\s*/i, "Shared genre fit: ")
    .replace(/^Audience behaviour signal:\s*/i, "Audience behaviour: ")
    .replace(/^Recommendation graph signal:\s*/i, "Recommendation graph: ")
    .replace(/^Story-shape signal:\s*/i, "Story fit: ")
    .replace(/^Strong audience quality signal:\s*/i, "Strong audience score: ")
    .replace(/^Solid audience quality signal:\s*/i, "Solid audience score: ")
    .trim();
}

function shortOverview(text: string | null | undefined, maxChars = 180): string {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (clean.length <= maxChars) return clean;
  return `${clean.slice(0, maxChars - 1).replace(/\s+\S*$/, "")}…`;
}

const SeoRecommendationCard: React.FC<Props> = ({
  anchorTitle,
  rec,
  variant = "feature",
  isFavorite,
  isWatchlist,
}) => {
  const posterUrl = useMemo(() => getPosterUrl(rec), [rec]);
  const year = useMemo(() => getYear(rec), [rec]);
  const genres = useMemo(() => getGenres(rec), [rec]);
  const slug = useMemo(() => slugifyTitle(rec.title), [rec.title]);
  const match = Math.max(62, Math.min(98, Number(rec.match_percent ?? 82)));
  const reasons = useMemo(
    () => (Array.isArray(rec.match_reasons) ? rec.match_reasons.map(cleanReason).filter(Boolean).slice(0, 5) : []),
    [rec.match_reasons]
  );
  const whyText = rec.why_recommended || rec.source_explanation || shortOverview(rec.overview, 260);
  const overview = shortOverview(rec.overview, variant === "feature" ? 260 : 160);

  return (
    <article className={`seo-rec-card seo-rec-card--${variant}`}>
      <div className="seo-rec-card__poster-wrap">
        <Link to={`/show/${rec.tmdb_id}`} className="seo-rec-card__poster-link" aria-label={`Open ${rec.title}`}>
          {posterUrl ? (
            <img src={posterUrl} alt={`${rec.title} poster`} className="seo-rec-card__poster" loading="lazy" />
          ) : (
            <div className="seo-rec-card__poster seo-rec-card__poster--empty">No image</div>
          )}
        </Link>

        <div className="seo-rec-card__rank">#{rec.rank ?? ""}</div>
        <div className="seo-rec-card__match-badge">
          <strong>{match}%</strong>
          <span>match</span>
        </div>
      </div>

      <div className="seo-rec-card__content">
        <div className="seo-rec-card__topline">
          <div>
            <h2 className="seo-rec-card__title">
              <Link to={`/show/${rec.tmdb_id}`}>{rec.title}</Link>
            </h2>
            <div className="seo-rec-card__meta">
              {year && <span>{year}</span>}
              {rec.vote_average != null && <span>TMDB {Number(rec.vote_average).toFixed(1)}</span>}
              {rec.vote_count != null && <span>{Number(rec.vote_count).toLocaleString()} votes</span>}
            </div>
          </div>

          <Link to={`/shows-like/${slug}`} className="seo-rec-card__similar-link">
            More like this →
          </Link>
        </div>

        {genres.length > 0 && (
          <div className="seo-rec-card__genres" aria-label="Genres">
            {genres.map((genre) => (
              <span key={genre}>{genre}</span>
            ))}
          </div>
        )}

        <section className="seo-rec-card__why">
          <h3>Why {rec.title} matches {anchorTitle}</h3>
          <p>{whyText}</p>
        </section>

        {reasons.length > 0 && (
          <section className="seo-rec-card__reasons">
            <h3>Match signals</h3>
            <ul>
              {reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </section>
        )}

        {overview && variant === "feature" && (
          <p className="seo-rec-card__overview">{overview}</p>
        )}

        <div className="seo-rec-card__actions">
          <Link to={`/show/${rec.tmdb_id}`} className="seo-rec-card__button seo-rec-card__button--primary">
            View details
          </Link>
          <Link to={`/shows-like/${slug}`} className="seo-rec-card__button">
            Find similar shows
          </Link>
          {(isFavorite || isWatchlist) && (
            <span className="seo-rec-card__saved">
              {isFavorite ? "♥ Favourite" : ""}{isFavorite && isWatchlist ? " · " : ""}{isWatchlist ? "🔖 Watchlist" : ""}
            </span>
          )}
        </div>
      </div>
    </article>
  );
};

export default SeoRecommendationCard;

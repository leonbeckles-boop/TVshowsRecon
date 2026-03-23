import React, { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import "./ShowCard.css";

export type ShowCardProps = {
  show: any;
  myRating?: number;
  isFav?: boolean;
  onToggleFav?: () => void | Promise<void>;
  onRate?: (rating: number) => void | Promise<void>;
  onHide?: () => void | Promise<void>;
  reasons?: string[] | string | null;

  isFavorite?: boolean;
  isNotInterested?: boolean;
  onToggleFavorite?: () => void;
  onToggleNotInterested?: () => void;

  isWatchlist?: boolean;
  onToggleWatchlist?: () => void | Promise<void>;

  variant?: "poster" | "glass";
};

function getTitle(show: any): string {
  return (
    show?.title ??
    show?.name ??
    show?.original_name ??
    show?.original_title ??
    show?.tmdb_title ??
    show?.details?.title ??
    "Untitled show"
  );
}

function getYear(show: any): string | null {
  const raw =
    show?.first_air_date ?? show?.release_date ?? show?.air_date ?? null;
  if (!raw || typeof raw !== "string" || raw.length < 4) return null;
  return raw.slice(0, 4);
}

function getGenres(show: any): string[] {
  if (Array.isArray(show?.genre_names)) return show.genre_names;
  if (Array.isArray(show?.genres)) {
    if (typeof show.genres[0] === "string") return show.genres as string[];
    return (show.genres as any[])
      .map((g) => g?.name)
      .filter(Boolean) as string[];
  }
  if (Array.isArray(show?.details?.genres)) {
    return (show.details.genres as any[])
      .map((g) => g?.name)
      .filter(Boolean) as string[];
  }
  return [];
}

const TMDB_IMG = "https://image.tmdb.org/t/p/w500";

function getPosterUrl(show: any): string | null {
  const direct = show?.poster_url ?? show?.posterUrl;
  if (direct && typeof direct === "string") return direct;

  const path =
    show?.poster_path ??
    show?.details?.poster_path ??
    show?.tmdb_poster_path ??
    null;

  if (path && typeof path === "string") {
    if (path.startsWith("http")) return path;
    return `${TMDB_IMG}${path}`;
  }
  return null;
}

function getTmdbRating(show: any) {
  const score =
    show?.vote_average ??
    show?.tmdb_vote_average ??
    show?.details?.vote_average ??
    null;

  const votes =
    show?.vote_count ??
    show?.tmdb_vote_count ??
    show?.details?.vote_count ??
    null;

  return {
    score: typeof score === "number" ? score : null,
    votes: typeof votes === "number" ? votes : null,
  };
}

function getTmdbId(show: any): number | null {
  const raw =
    show?.tmdb_id ??
    show?.details?.tmdb_id ??
    show?.external_id ??
    show?.show_id ??
    null;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : null;
}

const ShowCard: React.FC<ShowCardProps> = ({
  show,
  myRating,
  isFav,
  onToggleFav,
  onRate,
  onHide,
  reasons,
  isFavorite,
  isNotInterested,
  onToggleFavorite,
  onToggleNotInterested,
  isWatchlist,
  onToggleWatchlist,
}) => {
  const navigate = useNavigate();

  const title = useMemo(() => getTitle(show), [show]);
  const year = useMemo(() => getYear(show), [show]);
  const genres = useMemo(() => getGenres(show), [show]);
  const posterUrl = useMemo(() => getPosterUrl(show), [show]);
  const tmdb = useMemo(() => getTmdbRating(show), [show]);
  const tmdbId = useMemo(() => getTmdbId(show), [show]);

  const favActive = (isFav ?? isFavorite) ?? false;
  const handleFavToggle = onToggleFav ?? onToggleFavorite ?? undefined;

  const niActive = isNotInterested ?? false;
  const handleNiToggle = onHide ?? onToggleNotInterested ?? undefined;

  const watchlistActive = isWatchlist ?? false;
  const handleWatchlistToggle = onToggleWatchlist ?? undefined;

  const handleCardClick = () => {
    if (!tmdbId) return;

    navigate(`/show/${tmdbId}`);

    // ✅ FIX: offset scroll so header doesn't cover content
    setTimeout(() => {
      window.scrollTo({
        top: 0,
        behavior: "instant",
      });
    }, 50);
  };

  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-");

  return (
    <article
      className="show-card"
      onClick={handleCardClick}
      style={{ width: "100%", maxWidth: "240px" }}
    >
      <div className="show-card__poster">
        {posterUrl ? (
          <img src={posterUrl} alt={title} loading="lazy" />
        ) : (
          <div className="no-image">No image</div>
        )}

        <div className="show-card__poster-gradient" />

        {handleFavToggle && (
          <button
            className={
              "show-card__icon-btn show-card__icon-btn--fav" +
              (favActive ? " show-card__icon-btn--fav-active" : "")
            }
            onClick={(e) => {
              e.stopPropagation();
              handleFavToggle();
            }}
          >
            {favActive ? "♥" : "♡"}
          </button>
        )}

        {handleWatchlistToggle && (
          <button
            className={
              "show-card__icon-btn show-card__icon-btn--watchlist" +
              (watchlistActive ? " show-card__icon-btn--watchlist-active" : "")
            }
            onClick={(e) => {
              e.stopPropagation();
              handleWatchlistToggle();
            }}
          >
            {watchlistActive ? "🔖" : "📑"}
          </button>
        )}

        {handleNiToggle && (
          <button
            className="show-card__icon-btn show-card__icon-btn--hide"
            onClick={(e) => {
              e.stopPropagation();
              handleNiToggle();
            }}
          >
            ✕
          </button>
        )}

        {tmdb.score != null && tmdb.votes != null && (
          <div className="show-card__tmdb-chip">
            TMDB {tmdb.score.toFixed(1)}
          </div>
        )}
      </div>

      <div className="show-card__body">
        <div className="show-card__title">{title}</div>
        {year && <div className="show-card__year">{year}</div>}

        {/* 🚀 NEW: Find Similar CTA */}
        <a
          href={`/shows-like/${slug}`}
          className="show-card__similar-link"
          onClick={(e) => e.stopPropagation()}
        >
          🔎 Find similar
        </a>
      </div>
    </article>
  );
};

export default ShowCard;
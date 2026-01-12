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

  // Newer props used by ShowDetails / smart-similar
  isFavorite?: boolean;
  isNotInterested?: boolean;
  onToggleFavorite?: () => void;
  onToggleNotInterested?: () => void;

  /** "poster" = clean poster-only, "glass" = poster + glass title bar (reserved for future) */
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

function getTmdbRating(show: any): { score: number | null; votes: number | null } {
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

// Safely extract a TMDB id for navigation
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
  // new props (may or may not be provided)
  isFavorite,
  isNotInterested,
  onToggleFavorite,
  onToggleNotInterested,
}) => {
  const navigate = useNavigate();

  const title = useMemo(() => getTitle(show), [show]);
  const year = useMemo(() => getYear(show), [show]);
  const genres = useMemo(() => getGenres(show), [show]);
  const posterUrl = useMemo(() => getPosterUrl(show), [show]);
  const tmdb = useMemo(() => getTmdbRating(show), [show]);
  const tmdbId = useMemo(() => getTmdbId(show), [show]);

  const reasonsList: string[] = useMemo(() => {
    if (!reasons) return [];
    if (Array.isArray(reasons)) {
      return reasons.filter((r) => typeof r === "string" && r.trim().length > 0);
    }
    if (typeof reasons === "string") {
      return reasons
        .split(/[•|,]/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
    }
    return [];
  }, [reasons]);

  // 🔧 Derive effective favourite / not-interested handlers so both "old" and "new" props work
  const favActive = (isFav ?? isFavorite) ?? false;
  const handleFavToggle =
    onToggleFav ?? onToggleFavorite ?? undefined;

  const niActive = (isNotInterested ?? false);
  const handleNiToggle =
    onHide ?? onToggleNotInterested ?? undefined;

  const handleRatingChange = (ev: React.ChangeEvent<HTMLSelectElement>) => {
    ev.stopPropagation(); // don’t trigger navigation
    const val = Number(ev.target.value);
    if (!Number.isFinite(val) || val <= 0) {
      if (onRate) onRate(0);
      return;
    }
    if (onRate) onRate(val);
  };

  const handleCardClick = () => {
    if (!tmdbId) return;
    navigate(`/show/${tmdbId}`);
  };

  return (
    <article className="show-card" onClick={handleCardClick}>
      {/* Poster block */}
      <div className="show-card__poster">
        {posterUrl ? (
          <img src={posterUrl} alt={title} loading="lazy" />
        ) : (
          <div
            style={{
              width: "100%",
              height: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 12,
              color: "#9ca3af",
              background:
                "radial-gradient(circle at top, #020617 0%, #0f172a 55%)",
            }}
          >
            No image
          </div>
        )}

        <div className="show-card__poster-gradient" />

        {/* Favourite button (old + new props) */}
        {handleFavToggle && (
          <button
            type="button"
            className={
              "show-card__icon-btn show-card__icon-btn--fav" +
              (favActive ? " show-card__icon-btn--fav-active" : "")
            }
            onClick={(e) => {
              e.stopPropagation();
              handleFavToggle();
            }}
            title={favActive ? "Remove from favourites" : "Add to favourites"}
            aria-label={favActive ? "Remove from favourites" : "Add to favourites"}
          >
            {favActive ? "♥" : "♡"}
          </button>
        )}

        {/* Not-interested / hide button (old + new props) */}
        {handleNiToggle && (
          <button
            type="button"
            className="show-card__icon-btn show-card__icon-btn--hide"
            onClick={(e) => {
              e.stopPropagation();
              handleNiToggle();
            }}
            title={niActive ? "Undo Not Interested" : "Not interested"}
            aria-label={niActive ? "Undo Not Interested" : "Not interested"}
          >
            ✕
          </button>
        )}

        {/* TMDB score chip */}
        {tmdb.score != null && tmdb.votes != null && (
          <div className="show-card__tmdb-chip">
            <span className="show-card__tmdb-label">TMDB</span>
            <span className="show-card__tmdb-score">
              {tmdb.score.toFixed(1)}
            </span>
            <span className="show-card__tmdb-votes">
              ({tmdb.votes.toLocaleString()} votes)
            </span>
          </div>
        )}
      </div>

      {/* Body */}
      <div className="show-card__body">
        <div className="show-card__header-row">
          <div className="show-card__title-wrap">
            <div className="show-card__title">{title}</div>
            {year && <div className="show-card__year">{year}</div>}
          </div>
        </div>

        {genres.length > 0 && (
          <div className="show-card__genres">
            {genres.slice(0, 4).map((g) => (
              <span key={g} className="show-card__genre-chip">
                {g}
              </span>
            ))}
          </div>
        )}

        {show?.overview && (
          <div className="show-card__overview">{show.overview}</div>
        )}
      </div>

      {/* Footer */}
      <div className="show-card__footer">
        {onRate && (
          <div
            className="show-card__rating-block"
            onClick={(e) => e.stopPropagation()} // STOP tile click from firing
          >
            <div className="show-card__rating-label">Your rating</div>
            <select
              className="show-card__rating-select"
              value={myRating ?? 0}
              onClick={(e) => e.stopPropagation()} // extra safety
              onChange={handleRatingChange}
            >
              <option value={0}>No rating</option>
              {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
                <option key={n} value={n}>
                  {n} / 10
                </option>
              ))}
            </select>
          </div>
        )}

        {reasonsList.length > 0 && (
          <div className="show-card__reasons-hint">
            Why this: {reasonsList.join(" • ")}
          </div>
        )}
      </div>
    </article>
  );
};

export default ShowCard;

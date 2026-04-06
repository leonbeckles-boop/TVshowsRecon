import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiUrl } from "../api";

type Show = {
  tmdb_id: number;
  title: string;
  poster_path?: string | null;
};

type Props = {
  title: string;
  intro: string;
  endpoint: string;
};

function getTmdbId(x: unknown): number | null {
  const obj = x as {
    tmdb_id?: number | string;
    external_id?: number | string;
    show_id?: number | string;
    id?: number | string;
  };

  const cand = obj?.tmdb_id ?? obj?.external_id ?? obj?.show_id ?? obj?.id;
  const n = Number(cand);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export default function BestShows({ title, intro, endpoint }: Props) {
  const [shows, setShows] = useState<Show[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(null);

        const r = await fetch(apiUrl(endpoint));
        if (!r.ok) {
          throw new Error(`Failed to load page (${r.status})`);
        }

        const data: unknown = await r.json();

        const cleaned: Show[] = Array.isArray(data)
          ? data
              .map((s: unknown): Show | null => {
                const obj = s as {
                  title?: string;
                  poster_path?: string | null;
                  tmdb_id?: number | string;
                  external_id?: number | string;
                  show_id?: number | string;
                  id?: number | string;
                };

                const id = getTmdbId(obj);
                const showTitle = String(obj?.title ?? "").trim();

                if (!id || !showTitle) return null;

                return {
                  tmdb_id: id,
                  title: showTitle,
                  poster_path: obj?.poster_path ?? null,
                };
              })
              .filter((s): s is Show => s !== null)
              .filter(
                (s: Show, i: number, arr: Show[]) =>
                  arr.findIndex((x: Show) => x.tmdb_id === s.tmdb_id) === i
              )
              .sort((a, b) => a.title.localeCompare(b.title))
          : [];

        if (!cancelled) {
          setShows(cleaned);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Failed to load shows."
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [endpoint]);

  return (
    <div className="page-body shows-like-page">
      <div className="shows-like-hero">
        <h1 className="shows-like-title">{title}</h1>
        <p className="shows-like-intro">{intro}</p>
      </div>

      {loading && <div className="glass-card admin-empty">Loading...</div>}

      {!loading && error && (
        <div className="glass-card admin-empty">{error}</div>
      )}

      {!loading && !error && (
        <div className="tile-grid">
          {shows.map((s) => (
            <Link
              key={s.tmdb_id}
              to={`/show/${s.tmdb_id}`}
              className="show-card-link"
            >
              <div className="show-card">
                {s.poster_path ? (
                  <img
                    src={`https://image.tmdb.org/t/p/w500${s.poster_path}`}
                    alt={s.title}
                    loading="lazy"
                  />
                ) : (
                  <div className="show-card__poster-placeholder" aria-hidden="true" />
                )}

                <div className="show-card__title">{s.title}</div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
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

export default function BestShows({ title, intro, endpoint }: Props) {
  const [shows, setShows] = useState<Show[]>([]);

  useEffect(() => {
    async function load() {
      const r = await fetch(apiUrl(endpoint));
      const data = await r.json();
      setShows(data);
    }

    load();
  }, [endpoint]);

  return (
    <div className="page-body shows-like-page">
      <div className="shows-like-hero">
        <h1 className="shows-like-title">{title}</h1>
        <p className="shows-like-intro">{intro}</p>
      </div>

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
                />
              ) : (
                <div className="show-card__poster-placeholder">
                  {s.title}
                </div>
              )}

              <div className="show-card__title">{s.title}</div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
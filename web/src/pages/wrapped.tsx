import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import PageHeader from "../components/PageHeader";
import ShowCard from "../components/ShowCard";
import { apiUrl } from "../api";


const TMDB_IMG = "https://image.tmdb.org/t/p/w500";

type WrappedGenre = [string, number];

type WrappedShow = {
  tmdb_id: number;
  title: string;
  poster_path?: string | null;
  poster_url?: string | null;
  overview?: string | null;
  rating?: number;
};

type WrappedActivity = {
  most_active_month?: string;
  month_count?: Record<string, number>;
};

type WrappedPayload = {
  rating_count: number;
  favorite_count: number;
  average_rating: number | null;
  top_genres: WrappedGenre[];
  top_genre?: string | null;
  top_rated: WrappedShow[];
  lowest_rated: WrappedShow[];
  taste_cluster: string;
  activity: WrappedActivity;
  recommended_next: WrappedShow[];
  error?: string;
};

const BG_STYLE: React.CSSProperties = {
  minHeight: "100vh",
  width: "100%",
  paddingTop: "128px",
  backgroundColor: "#020617",
  backgroundImage: [
    "radial-gradient(circle at top center, rgba(30,58,138,0.45) 0%, rgba(2,6,23,0.9) 55%, #020617 100%)",
    "linear-gradient(to right, rgba(148,163,184,0.09) 1px, transparent 1px)",
    "linear-gradient(to bottom, rgba(148,163,184,0.09) 1px, transparent 1px)",
  ].join(", "),
  backgroundSize: "auto, 90px 90px, 90px 90px",
  backgroundPosition: "center top, 0 64px, 0 64px",
  backgroundBlendMode: "normal, soft-light, soft-light",
  color: "#e5e7eb",
};

function posterUrl(show: WrappedShow): string | undefined {
  // 1) If poster_url is already a full URL, use it
  const url = (show as any).poster_url;
  if (url && typeof url === "string") {
    if (url.startsWith("http://") || url.startsWith("https://")) {
      return url;
    }
    // If it's just a TMDb path, normalise it
    return `${TMDB_IMG}${url}`;
  }

  // 2) Fallback to poster_path
  const path = show.poster_path;
  if (path && typeof path === "string") {
    if (path.startsWith("http://") || path.startsWith("https://")) {
      return path;
    }
    return `${TMDB_IMG}${path}`;
  }

  return undefined;
}


const WrappedPage: React.FC = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<WrappedPayload | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // redirect to login if not authenticated
  useEffect(() => {
    if (!user) {
      navigate("/login", { replace: true, state: { from: "/wrapped" } });
    }
  }, [user, navigate]);

  useEffect(() => {
    if (!user) return;

    const fetchWrapped = async () => {
      try {
        setLoading(true);
        setError(null);
        const resp = await fetch(apiUrl(`/wrapped/${user.id}`), {
          headers: {
          Accept: "application/json",
          },
        });
        if (!resp.ok) {
          throw new Error(`Failed to load wrapped (${resp.status})`);
        }
        const json = (await resp.json()) as WrappedPayload;
        if (json.error) {
          setError(json.error);
        }
        setData(json);
      } catch (e: any) {
        setError(e?.message || "Failed to load your Wrapped.");
        setData(null);
      } finally {
        setLoading(false);
      }
    };

    void fetchWrapped();
  }, [user]);

  const topGenresWithPercent = useMemo(() => {
    if (!data || !data.top_genres || data.top_genres.length === 0) return [];
    const total = data.top_genres.reduce((acc, [, count]) => acc + count, 0);
    if (!total) return [];
    return data.top_genres.map(([genre, count]) => ({
      genre,
      count,
      pct: Math.round((count / total) * 100),
    }));
  }, [data]);

  if (!user) {
    // redirect effect will run; render nothing here
    return null;
  }

  return (
    <>
      <PageHeader
        title="Your WhatNext Wrapped"
        subtitle="A cinematic recap of your TV taste and habits."
        centered
      />

      <div style={BG_STYLE}>
        <main className="mx-auto flex max-w-6xl flex-col gap-10 px-4 pb-16 pt-6">
          {loading && (
            <section className="rounded-2xl border border-slate-700 bg-slate-900/70 px-5 py-4 text-sm text-slate-200 shadow-lg shadow-slate-950/70">
              Loading your Wrapped…
            </section>
          )}

          {error && !loading && (
            <section className="rounded-2xl border border-red-500/70 bg-red-950/80 px-5 py-4 text-sm text-red-100 shadow-lg shadow-red-950/70">
              {error}
            </section>
          )}

          {!loading && !error && data && (
            <>
              {/* HERO */}
              <section className="rounded-3xl border border-cyan-400/30 bg-gradient-to-br from-slate-900/90 via-slate-950/95 to-slate-900/90 px-6 py-8 shadow-2xl shadow-cyan-900/60">
                <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
                  <div className="space-y-3">
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
                      WhatNext Wrapped
                    </p>
                    <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight text-slate-50">
                      Your TV year in review
                    </h2>
                    <p className="max-w-xl text-sm md:text-base text-slate-200/90">
                      Here&apos;s how your taste in TV shaped up — from your
                      favourite genres to the shows you couldn&apos;t stop
                      rating.
                    </p>
                    {data.taste_cluster && (
                      <p className="text-sm md:text-base text-cyan-200/90">
                        {data.taste_cluster}
                      </p>
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-4 md:grid-cols-2 md:min-w-[260px]">
                    <div className="rounded-2xl bg-slate-900/80 px-4 py-3 text-center border border-slate-700/70">
                      <div className="text-xs uppercase tracking-wide text-slate-400">
                        Shows rated
                      </div>
                      <div className="mt-1 text-2xl font-bold text-slate-50">
                        {data.rating_count ?? 0}
                      </div>
                    </div>
                    <div className="rounded-2xl bg-slate-900/80 px-4 py-3 text-center border border-slate-700/70">
                      <div className="text-xs uppercase tracking-wide text-slate-400">
                        Favourites
                      </div>
                      <div className="mt-1 text-2xl font-bold text-slate-50">
                        {data.favorite_count ?? 0}
                      </div>
                    </div>
                    <div className="rounded-2xl bg-slate-900/80 px-4 py-3 text-center border border-slate-700/70">
                      <div className="text-xs uppercase tracking-wide text-slate-400">
                        Avg rating
                      </div>
                      <div className="mt-1 text-2xl font-bold text-slate-50">
                        {data.average_rating ?? "–"}
                      </div>
                    </div>
                    <div className="rounded-2xl bg-slate-900/80 px-4 py-3 text-center border border-slate-700/70">
                      <div className="text-xs uppercase tracking-wide text-slate-400">
                        Top genre
                      </div>
                      <div className="mt-1 text-sm font-semibold text-cyan-300">
                        {data.top_genre || "Mixed"}
                      </div>
                    </div>
                  </div>
                </div>
              </section>

              {/* TOP GENRES */}
              {topGenresWithPercent.length > 0 && (
                <section className="space-y-4">
                  <div>
                    <h3 className="text-2xl font-bold text-slate-50 tracking-tight">
                      Your top genres
                    </h3>
                    <p className="text-sm text-slate-300">
                      Based on the shows you&apos;ve rated and favourited.
                    </p>
                  </div>

                  <div className="space-y-2">
                    {topGenresWithPercent.map((g) => (
                      <div key={g.genre} className="space-y-1">
                        <div className="flex items-baseline justify-between">
                          <span className="text-sm font-semibold text-slate-100">
                            {g.genre}
                          </span>
                          <span className="text-xs text-slate-400">
                            {g.pct}% ({g.count} show
                            {g.count === 1 ? "" : "s"})
                          </span>
                        </div>
                        <div className="h-2 rounded-full bg-slate-800/80 overflow-hidden">
                          <div
                            className="h-full rounded-full bg-gradient-to-r from-cyan-400 via-sky-500 to-indigo-500"
                            style={{ width: `${g.pct}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {/* TOP RATED */}
              {data.top_rated && data.top_rated.length > 0 && (
                <section className="space-y-4">
                  <div className="flex items-baseline justify-between gap-2">
                    <div>
                      <h3 className="text-2xl font-bold text-slate-50 tracking-tight">
                        Your highest-rated shows
                      </h3>
                      <p className="text-sm text-slate-300">
                        The series that impressed you the most.
                      </p>
                    </div>
                  </div>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns:
                        "repeat(auto-fill, minmax(220px, 1fr))",
                      gap: "1.0rem",
                      alignItems: "flex-start",
                    }}
                  >
                    {data.top_rated.map((s) => (
                      <ShowCard
                        key={s.tmdb_id}
                        show={{
                          ...s,
                          poster_url: posterUrl(s),
                        }}
                      />
                    ))}
                  </div>
                </section>
              )}

              {/* LOWEST RATED */}
              {data.lowest_rated && data.lowest_rated.length > 0 && (
                <section className="space-y-4">
                  <div>
                    <h3 className="text-2xl font-bold text-slate-50 tracking-tight">
                      Not everything was a hit
                    </h3>
                    <p className="text-sm text-slate-300">
                      A few shows didn&apos;t quite land for you.
                    </p>
                  </div>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns:
                        "repeat(auto-fill, minmax(220px, 1fr))",
                      gap: "1.0rem",
                      alignItems: "flex-start",
                    }}
                  >
                    {data.lowest_rated.map((s) => (
                      <ShowCard
                        key={s.tmdb_id}
                        show={{
                          ...s,
                          poster_url: posterUrl(s),
                        }}
                      />
                    ))}
                  </div>
                </section>
              )}

              {/* ACTIVITY */}
              {data.activity && data.activity.most_active_month && (
                <section className="space-y-3">
                  <h3 className="text-2xl font-bold text-slate-50 tracking-tight">
                    When you were most active
                  </h3>
                  <p className="text-sm text-slate-300">
                    Your busiest month for rating shows was{" "}
                    <span className="font-semibold text-cyan-300">
                      {data.activity.most_active_month}
                    </span>
                    .
                  </p>
                </section>
              )}

              {/* RECOMMENDED NEXT */}
              {data.recommended_next && data.recommended_next.length > 0 && (
                <section className="space-y-4">
                  <div className="flex items-baseline justify-between gap-2">
                    <div>
                      <h3 className="text-2xl font-bold text-slate-50 tracking-tight">
                        WhatNext thinks you&apos;ll love next
                      </h3>
                      <p className="text-sm text-slate-300">
                        Hand-picked based on your top genres and highly rated
                        shows.
                      </p>
                    </div>
                  </div>

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns:
                        "repeat(auto-fill, minmax(220px, 1fr))",
                      gap: "1.0rem",
                      alignItems: "flex-start",
                    }}
                  >
                    {data.recommended_next.map((s) => (
                      <ShowCard
                        key={s.tmdb_id}
                        show={{
                          ...s,
                          poster_url: posterUrl(s),
                        }}
                      />
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
        </main>
      </div>
    </>
  );
};

export default WrappedPage;

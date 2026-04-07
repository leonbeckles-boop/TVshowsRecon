import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

type TopRatedShow = {
  tmdb_id: number;
  title: string;
  poster_path?: string | null;
  poster_url?: string | null;
  avg_rating: number;
  ratings_count: number;
  weighted_score: number;
};

const API_BASE =
  (import.meta as any)?.env?.VITE_API_BASE?.replace(/\/+$/, "") || "/api";

export default function TopRated() {
  const [shows, setShows] = useState<TopRatedShow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [minVotes, setMinVotes] = useState(3);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError("");

        const res = await fetch(
          `${API_BASE}/shows/top-rated?limit=10&min_votes=${minVotes}`,
          {
            credentials: "include",
          }
        );

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();

        if (!cancelled) {
          setShows(Array.isArray(data) ? data : []);
        }
      } catch (err) {
        console.error("Failed to load top rated shows", err);
        if (!cancelled) {
          setError("Could not load top rated shows right now.");
          setShows([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [minVotes]);

  const pageTitle = useMemo(() => {
    if (shows.length >= 10) return "Top 10 Rated Shows by WhatNext Users";
    return "Top Rated Shows by WhatNext Users";
  }, [shows.length]);

  return (
    <main className="mx-auto w-full max-w-7xl px-4 pb-12 pt-28 sm:px-6 lg:px-8">
      <section
        style={{
          border: "1px solid rgba(148,163,184,0.18)",
          background:
            "linear-gradient(180deg, rgba(15,23,42,0.82) 0%, rgba(15,23,42,0.62) 100%)",
          backdropFilter: "blur(14px)",
          WebkitBackdropFilter: "blur(14px)",
          borderRadius: 24,
          boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
          padding: "20px",
          marginBottom: "20px",
        }}
      >
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div className="max-w-3xl">
            <p
              style={{
                fontSize: 12,
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                color: "#93c5fd",
                marginBottom: 8,
              }}
            >
              Community favourites
            </p>

            <h1
              style={{
                fontSize: "clamp(1.75rem, 3vw, 2.5rem)",
                lineHeight: 1.05,
                fontWeight: 800,
                color: "#f8fafc",
                margin: 0,
              }}
            >
              {pageTitle}
            </h1>

            <p
              style={{
                marginTop: 12,
                marginBottom: 0,
                color: "#cbd5e1",
                fontSize: 15,
                lineHeight: 1.7,
              }}
            >
              These rankings are based on real ratings from WhatNext users and
              use a weighted score so shows with more ratings rise above
              one-off perfect scores.
            </p>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              flexWrap: "wrap",
            }}
          >
            <label
              htmlFor="minVotes"
              style={{
                fontSize: 13,
                color: "#cbd5e1",
                fontWeight: 600,
              }}
            >
              Minimum ratings
            </label>

            <select
              id="minVotes"
              value={minVotes}
              onChange={(e) => setMinVotes(Number(e.target.value))}
              style={{
                fontSize: 14,
                padding: "9px 14px",
                borderRadius: 999,
                border: "1px solid rgba(148,163,184,0.35)",
                background: "rgba(255,255,255,0.96)",
                color: "#0f172a",
                outline: "none",
                fontWeight: 600,
              }}
            >
              <option value={2}>2+</option>
              <option value={3}>3+</option>
              <option value={4}>4+</option>
              <option value={5}>5+</option>
            </select>
          </div>
        </div>
      </section>

      {loading ? (
        <section
          style={{
            border: "1px solid rgba(148,163,184,0.16)",
            background: "rgba(15,23,42,0.6)",
            backdropFilter: "blur(14px)",
            WebkitBackdropFilter: "blur(14px)",
            borderRadius: 24,
            padding: "28px 20px",
            color: "#cbd5e1",
          }}
        >
          Loading top rated shows...
        </section>
      ) : error ? (
        <section
          style={{
            border: "1px solid rgba(239,68,68,0.25)",
            background: "rgba(127,29,29,0.18)",
            backdropFilter: "blur(14px)",
            WebkitBackdropFilter: "blur(14px)",
            borderRadius: 24,
            padding: "20px",
            color: "#fecaca",
          }}
        >
          {error}
        </section>
      ) : shows.length === 0 ? (
        <section
          style={{
            border: "1px solid rgba(148,163,184,0.16)",
            background: "rgba(15,23,42,0.6)",
            backdropFilter: "blur(14px)",
            WebkitBackdropFilter: "blur(14px)",
            borderRadius: 24,
            padding: "24px 20px",
            color: "#cbd5e1",
          }}
        >
          Not enough rated shows yet for this threshold. Try lowering the
          minimum ratings filter.
        </section>
      ) : (
        <section
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
            gap: 16,
          }}
        >
          {shows.map((show, index) => {
            const poster =
              show.poster_url ||
              (show.poster_path
                ? `https://image.tmdb.org/t/p/w500/${show.poster_path.replace(
                    /^\/+/,
                    ""
                  )}`
                : null);

            return (
              <Link
                key={show.tmdb_id}
                to={`/show/${show.tmdb_id}`}
                style={{
                  textDecoration: "none",
                  color: "inherit",
                  minWidth: 0,
                }}
              >
                <article
                  style={{
                    height: "100%",
                    border: "1px solid rgba(148,163,184,0.16)",
                    background:
                      "linear-gradient(180deg, rgba(15,23,42,0.82) 0%, rgba(15,23,42,0.62) 100%)",
                    backdropFilter: "blur(14px)",
                    WebkitBackdropFilter: "blur(14px)",
                    borderRadius: 22,
                    boxShadow: "0 18px 40px rgba(0,0,0,0.28)",
                    overflow: "hidden",
                    transition: "transform 0.18s ease, box-shadow 0.18s ease",
                  }}
                >
                  <div
                    style={{
                      position: "relative",
                      aspectRatio: "2 / 3",
                      background:
                        "linear-gradient(180deg, rgba(30,41,59,0.9), rgba(15,23,42,1))",
                    }}
                  >
                    {poster ? (
                      <img
                        src={poster}
                        alt={show.title}
                        loading="lazy"
                        style={{
                          width: "100%",
                          height: "100%",
                          objectFit: "cover",
                          display: "block",
                        }}
                      />
                    ) : (
                      <div
                        style={{
                          width: "100%",
                          height: "100%",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          padding: 16,
                          textAlign: "center",
                          color: "#cbd5e1",
                          fontWeight: 700,
                          fontSize: 14,
                        }}
                      >
                        No poster available
                      </div>
                    )}

                    <div
                      style={{
                        position: "absolute",
                        top: 10,
                        left: 10,
                        minWidth: 38,
                        height: 38,
                        borderRadius: 999,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        background: "rgba(2,6,23,0.82)",
                        border: "1px solid rgba(255,255,255,0.14)",
                        color: "#f8fafc",
                        fontWeight: 800,
                        fontSize: 14,
                        boxShadow: "0 8px 20px rgba(0,0,0,0.25)",
                      }}
                    >
                      #{index + 1}
                    </div>
                  </div>

                  <div style={{ padding: 14 }}>
                    <h2
                      style={{
                        margin: 0,
                        fontSize: 16,
                        lineHeight: 1.3,
                        fontWeight: 800,
                        color: "#f8fafc",
                        minHeight: 42,
                      }}
                    >
                      {show.title}
                    </h2>

                    <div
                      style={{
                        display: "grid",
                        gap: 8,
                        marginTop: 12,
                      }}
                    >
                      <StatPill
                        label="Average rating"
                        value={`${show.avg_rating.toFixed(2)} ★`}
                      />
                      <StatPill
                        label="User ratings"
                        value={`${show.ratings_count}`}
                      />
                      <StatPill
                        label="Weighted score"
                        value={show.weighted_score.toFixed(2)}
                      />
                    </div>
                  </div>
                </article>
              </Link>
            );
          })}
        </section>
      )}
    </main>
  );
}

function StatPill({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: 12,
        padding: "10px 12px",
        borderRadius: 14,
        background: "rgba(255,255,255,0.06)",
        border: "1px solid rgba(148,163,184,0.14)",
      }}
    >
      <span
        style={{
          fontSize: 12,
          color: "#cbd5e1",
          fontWeight: 600,
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontSize: 13,
          color: "#f8fafc",
          fontWeight: 800,
          whiteSpace: "nowrap",
        }}
      >
        {value}
      </span>
    </div>
  );
}
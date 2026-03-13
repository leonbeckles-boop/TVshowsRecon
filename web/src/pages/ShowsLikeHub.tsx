import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiUrl } from "../api";

type SeedGroup = {
  heading: string;
  description: string;
  shows: string[];
};

const GROUPS: SeedGroup[] = [
  {
    heading: "Crime & Drama",
    description: "Dark antiheroes, prestige drama, crime sagas and intense character stories.",
    shows: [
      "Breaking Bad",
      "Better Call Saul",
      "Ozark",
      "The Wire",
      "The Sopranos",
      "True Detective",
      "Peaky Blinders",
      "Top Boy",
      "Dexter",
      "The Shield",
      "The Night Of",
      "Black Bird",
    ],
  },
  {
    heading: "Sci-Fi & Mystery",
    description: "Mind-bending, atmospheric and high-concept shows with mystery at the core.",
    shows: [
      "Dark",
      "Severance",
      "Black Mirror",
      "Lost",
      "Twin Peaks",
      "The X-Files",
      "Silo",
      "Fallout",
      "The Last of Us",
      "Stranger Things",
      "The 100",
      "The Mandalorian",
    ],
  },
  {
    heading: "Prestige TV & Thrillers",
    description: "Sharp writing, tension, standout performances and must-watch modern series.",
    shows: [
      "Fargo",
      "Succession",
      "The White Lotus",
      "House of the Dragon",
      "Squid Game",
      "The Penguin",
      "Tokyo Vice",
      "Mr. Robot",
      "The Night Manager",
      "Black Sails",
      "The Last Kingdom",
      "Dark Winds",
    ],
  },
  {
    heading: "Comedy & Offbeat",
    description: "Smart, funny and addictive shows with strong fan followings.",
    shows: [
      "The Office",
      "Silicon Valley",
      "Curb Your Enthusiasm",
      "It's Always Sunny in Philadelphia",
      "Modern Family",
      "Only Murders in the Building",
      "South Park",
      "Buffy the Vampire Slayer",
    ],
  },
];

function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export default function ShowsLikeHub() {

  const [shows, setShows] = useState<any[]>([]);

  useEffect(() => {
    async function load() {
      const r = await fetch(apiUrl("/seo/shows-like-index"));
      const data = await r.json();
      setShows(data);
    }

    load();
  }, []);

  return (
    <div className="page-body shows-like-page">

      <section className="shows-like-hub-hero">
        <h1 className="shows-like-title">Find Shows Like Your Favourites</h1>
        <p className="shows-like-intro">
          Browse curated pages for popular TV series and discover what to watch next.
          Each page uses WhatNext recommendation signals to surface similar shows. !! Click on your favourite shows below and find similar shows !!
        </p>
      </section>

      <div className="shows-like-hub-groups">

        {GROUPS.map((group) => (
          <section key={group.heading} className="shows-like-hub-section glass-card">

            <div className="shows-like-hub-section__header">
              <h2 className="shows-like-hub-section__title">{group.heading}</h2>
              <p className="shows-like-hub-section__desc">{group.description}</p>
            </div>

            <div className="shows-like-hub-links">
              {group.shows.map((title) => (
                <Link
                  key={title}
                  to={`/shows-like/${slugify(title)}`}
                  className="shows-like-hub-link"
                >
                 {title}
                </Link>
              ))}
            </div>

          </section>
        ))}

      </div>

      {/* Auto SEO links */}
      {shows.length > 0 && (
        <section className="shows-like-hub-section glass-card">

          <div className="shows-like-hub-section__header">
            <h2 className="shows-like-hub-section__title">More Shows</h2>
            <p className="shows-like-hub-section__desc">
              Browse more shows people frequently search for.
            </p>
          </div>

          <div className="shows-like-hub-links">
            {shows.map((s) => (
              <Link
                key={s.tmdb_id}
                to={`/shows-like/${slugify(s.title)}`}
                className="shows-like-hub-link"
              >
                 {s.title}
              </Link>
            ))}
          </div>

        </section>
      )}

    </div>
  );
}
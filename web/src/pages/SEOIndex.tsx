import React from "react";

const slugs = [
  "breaking-bad",
  "better-call-saul",
  "ozark",
  "the-wire",
  "dark",
  "stranger-things",
  "the-sopranos",
  "the-white-lotus",
  "the-night-of",
  "fargo",
  "true-detective",
  "mindhunter",
  "narcos",
  "peaky-blinders",
  "succession",
  "game-of-thrones",
  "house-of-the-dragon",
  "the-boys",
  "fallout",
  "severance",
  "black-mirror",
  "westworld",
  "the-leftovers",
  "lost",
  "the-americans",
  "mr-robot",
  "dexter",
  "barry",
  "atlanta",
  "the-bear",
  "yellowjackets",
  "euphoria",
  "mad-men",
  "boardwalk-empire",
  "chernobyl",
  "the-last-of-us",
  "andor",
  "the-mandalorian",
  "ahsoka",
  "obi-wan-kenobi"
];

function slugToTitle(slug: string) {
  return slug
    .split("-")
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export default function SEOIndex() {
  return (
    <div className="page-container">
      <h1>TV Show Recommendations</h1>

      <p>
        Browse TV show recommendation pages from WhatNext. Each page helps you
        discover shows similar to your favourites.
      </p>

      <ul style={{ columns: 3 }}>
        {slugs.map(slug => (
          <li key={slug}>
            <a href={`/shows-like/${slug}`}>
              Shows Like {slugToTitle(slug)}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
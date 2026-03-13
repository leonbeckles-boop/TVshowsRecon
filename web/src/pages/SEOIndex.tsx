import React from "react";

const slugs = [
  "breaking-bad","better-call-saul","ozark","the-wire","dark","stranger-things",
  "the-sopranos","the-white-lotus","the-night-of","fargo","true-detective",
  "mindhunter","narcos","peaky-blinders","succession","game-of-thrones",
  "house-of-the-dragon","the-boys","fallout","severance","black-mirror",
  "westworld","the-leftovers","lost","the-americans","mr-robot","dexter",
  "barry","atlanta","the-bear","yellowjackets","euphoria","mad-men",
  "boardwalk-empire","chernobyl","the-last-of-us","andor","the-mandalorian",
  "ahsoka","obi-wan-kenobi","six-feet-under","the-shield","bosch","reacher",
  "jack-ryan","homeland","24","prison-break","sons-of-anarchy","mayans-m-c",
  "justified","deadwood","banshee","hannibal","sherlock","luther",
  "line-of-duty","broadchurch","happy-valley","bodyguard","slow-horses",
  "killing-eve","the-fall","top-boy","gangs-of-london","money-heist","berlin",
  "squid-game","alice-in-borderland","kingdom","all-of-us-are-dead",
  "the-walking-dead","fear-the-walking-dead","the-handmaid-s-tale",
  "house-of-cards","the-crown","downton-abbey","the-queen-s-gambit",
  "mare-of-easttown","big-little-lies","sharp-objects","only-murders-in-the-building",
  "monk","psych","elementary","castle","person-of-interest","fringe",
  "the-x-files","twin-peaks","silo","foundation","for-all-mankind",
  "the-expanse","battlestar-galactica","firefly","doctor-who","torchwood",
  "orphan-black","humans","altered-carbon","travelers","manifest",
  "from","1899","bodies","archive-81","sense8","the-oa","russian-doll",
  "upload","utopia","the-terror","the-outsider","penny-dreadful",
  "american-horror-story","the-haunting-of-hill-house","the-haunting-of-bly-manor",
  "midnight-mass","the-midnight-club","wednesday","you","dead-to-me",
  "good-girls","the-good-place","ted-lasso","shrinking","parks-and-recreation",
  "the-office","brooklyn-nine-nine","superstore","abbott-elementary",
  "community","arrested-development","schitt-s-creek","fleabag","derry-girls",
  "after-life","the-righteous-gemstones","silicon-valley","mythic-quest",
  "beef","the-gentlemen","the-penguin","gomorrah","suburra-blood-on-rome",
  "zerozerozero","snowfall","power","power-book-ii-ghost","the-last-kingdom",
  "vikings","vikings-valhalla","black-sails","spartacus","rome",
  "the-tudors","outlander","yellowstone","1883","1923","mayor-of-kingstown",
  "tulsa-king","ray-donovan","animal-kingdom","billions","industry",
  "the-morning-show","bad-sisters","presumed-innocent","hijack",
  "defending-jacob","your-honor","the-undoing","the-sinner","the-rookie",
  "blue-lights","this-is-us","normal-people","one-day","bridgerton",
  "queen-charlotte-a-bridgerton-story","sex-education","skins","misfits",
  "a-teacher","the-affair","wecrashed","pam-and-tommy","dopesick",
  "painkiller","the-dropout"
];

function slugToTitle(slug: string) {
  return slug
    .split("-")
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export default function SEOIndex() {
  return (
    <div className="page-container" style={{ maxWidth: 1100, margin: "0 auto" }}>
      <h1>TV Show Recommendation Pages</h1>

      <p>
        Explore WhatNext's collection of TV recommendation guides. Each page
        helps you discover shows similar to popular series such as Breaking Bad,
        Dark, Fargo and many more.
      </p>

      <div
        style={{
          columnCount: 4,
          columnGap: "40px",
          marginTop: "30px"
        }}
      >
        {slugs.map((slug) => (
          <div key={slug} style={{ breakInside: "avoid", marginBottom: "8px" }}>
            <a href={`/shows-like/${slug}`}>
              Shows Like {slugToTitle(slug)}
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}
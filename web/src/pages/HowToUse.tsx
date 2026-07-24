import React from "react";
import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";

export default function HowToUse() {
  const pageWrap: React.CSSProperties = {
    paddingTop: 140,
    paddingLeft: 16,
    paddingRight: 16,
    paddingBottom: 48,
    maxWidth: 1180,
    margin: "0 auto",
  };

  const glass: React.CSSProperties = {
    borderRadius: 18,
    border: "1px solid rgba(255,255,255,0.10)",
    background: "rgba(255,255,255,0.04)",
    boxShadow: "0 10px 40px rgba(0,0,0,0.35)",
    backdropFilter: "blur(8px)",
  };

  const h1: React.CSSProperties = {
    fontSize: "clamp(30px, 4vw, 42px)",
    lineHeight: 1.1,
    margin: 0,
  };

  const h2: React.CSSProperties = {
    fontSize: 24,
    margin: 0,
  };

  const sub: React.CSSProperties = {
    opacity: 0.8,
    marginTop: 10,
    lineHeight: 1.6,
    maxWidth: 780,
  };

  const pill: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    padding: "8px 12px",
    borderRadius: 999,
    border: "1px solid rgba(255,255,255,0.12)",
    background: "rgba(255,255,255,0.06)",
    fontSize: 13,
  };

  const grid3: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
    gap: 14,
    marginTop: 18,
  };

  const grid2: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
    gap: 14,
    marginTop: 18,
  };

  const card: React.CSSProperties = {
    ...glass,
    padding: 18,
  };

  const titleSm: React.CSSProperties = {
    fontSize: 17,
    margin: 0,
    fontWeight: 700,
  };

  const text: React.CSSProperties = {
    opacity: 0.82,
    marginTop: 8,
    lineHeight: 1.55,
  };

  const list: React.CSSProperties = {
    opacity: 0.8,
    marginTop: 12,
    paddingLeft: 20,
    lineHeight: 1.65,
  };

  const actions: React.CSSProperties = {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
    marginTop: 16,
  };

  const btnPrimary: React.CSSProperties = {
    ...pill,
    cursor: "pointer",
    textDecoration: "none",
    border: "1px solid rgba(56,189,248,0.35)",
    background: "rgba(56,189,248,0.18)",
    color: "rgba(240,250,255,0.98)",
    fontWeight: 700,
  };

  const btnSecondary: React.CSSProperties = {
    ...pill,
    cursor: "pointer",
    textDecoration: "none",
    color: "rgba(255,255,255,0.92)",
  };

  const stepBadge: React.CSSProperties = {
    width: 30,
    height: 30,
    borderRadius: 999,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 13,
    fontWeight: 800,
    border: "1px solid rgba(56,189,248,0.35)",
    background: "rgba(56,189,248,0.18)",
    color: "rgba(240,250,255,0.98)",
    flex: "0 0 auto",
  };

  const highlight: React.CSSProperties = {
    ...glass,
    padding: 20,
    marginTop: 16,
    border: "1px solid rgba(56,189,248,0.22)",
    background:
      "linear-gradient(135deg, rgba(56,189,248,0.10), rgba(255,255,255,0.035))",
  };

  return (
    <div>
      <PageHeader
        title="How WhatNext works"
        subtitle="Build your taste profile, then let WhatNext find shows that fit you — not everyone else."
      />

      <div style={pageWrap}>
        <div style={{ ...pill, marginBottom: 10 }}>New to WhatNext? Start here ↓</div>

        <section style={{ ...glass, padding: 22 }}>
          <h1 style={h1}>Stop scrolling. Start with shows you already love.</h1>
          <div style={sub}>
            WhatNext learns your taste from the shows you favourite, the ratings you give and the shows you hide.
            Those choices build a personal taste profile that powers your recommendations.
          </div>

          <div style={highlight}>
            <div style={{ ...titleSm, fontSize: 19 }}>The simple idea</div>
            <div style={{ ...text, fontSize: 15 }}>
              Tell WhatNext <b>what you love</b>, <b>how much you loved it</b> and <b>what you are not interested in</b>.
              We use those signals to narrow thousands of shows into a more useful shortlist for you.
            </div>
          </div>

          <div style={grid3}>
            <div style={card}>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div style={stepBadge}>1</div>
                <div style={titleSm}>Create your free account</div>
              </div>
              <div style={text}>
                Start by creating an account with just your <b>email address and a password</b>. That’s it — once you’re
                signed in, you can save favourites, rate shows and build your personal taste profile.
              </div>
              <div style={actions}>
                <Link to="/login" style={btnPrimary}>
                  Create account / sign in
                </Link>
              </div>
            </div>

            <div style={card}>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div style={stepBadge}>2</div>
                <div style={titleSm}>Add shows you know</div>
              </div>
              <div style={text}>
                Search for shows you have already watched and add the ones you genuinely loved to your favourites.
                These give WhatNext the clearest signal about your taste.
              </div>
              <div style={actions}>
                <Link to="/search" style={btnPrimary}>
                  Search for shows
                </Link>
              </div>
            </div>

            <div style={card}>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div style={stepBadge}>3</div>
                <div style={titleSm}>Rate and refine your taste</div>
              </div>
              <div style={text}>
                Rate what you have watched and use “not interested” when something is not for you. Every choice gives
                WhatNext more information about what fits your taste.
              </div>
              <ul style={list}>
                <li><b>Favourites</b> tell us what you want more of.</li>
                <li><b>Ratings</b> add context — a 10/10 means something different from a 6/10.</li>
                <li><b>Not interested</b> helps move recommendations away from things you would not watch.</li>
              </ul>
            </div>
          </div>

          <div style={{ ...highlight, marginTop: 14 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <div style={stepBadge}>4</div>
              <div style={{ ...titleSm, fontSize: 19 }}>Get recommendations built around you</div>
            </div>
            <div style={{ ...text, maxWidth: 780 }}>
              Once you have added a few favourites and ratings, open Recommendations to see shows selected around your
              taste profile. Keep favouriting, rating and hiding shows to keep refining what WhatNext knows about you.
            </div>
            <div style={actions}>
              <Link to="/recs" style={btnPrimary}>
                See my recommendations
              </Link>
              <Link to="/favorites" style={btnSecondary}>
                View my favourites
              </Link>
            </div>
          </div>
        </section>

        <section style={{ marginTop: 18 }}>
          <div style={grid2}>
            <div style={card}>
              <h2 style={h2}>What makes a good taste profile?</h2>
              <div style={text}>
                Variety helps. Add the shows that really represent what you enjoy rather than filling your favourites
                with everything you have ever watched.
              </div>
              <ul style={list}>
                <li>Add around <b>5 favourites</b> to get started.</li>
                <li>Rate several shows you know well.</li>
                <li>Include favourites from different genres you genuinely enjoy.</li>
                <li>Keep using “not interested” when a suggestion misses the mark.</li>
              </ul>
            </div>

            <div style={card}>
              <h2 style={h2}>WhatNext is not just a popularity list</h2>
              <div style={text}>
                Popular shows are easy to find anywhere. WhatNext is designed to help answer a harder question:
                <b> “What should I watch next based on the things I already know I like?”</b>
              </div>
              <ul style={list}>
                <li>Looks for connections between the shows you enjoy.</li>
                <li>Uses your own favourites and ratings as the starting point.</li>
                <li>Lets you actively remove suggestions that do not fit.</li>
                <li>Helps surface shows you may not have thought to search for.</li>
              </ul>
            </div>
          </div>
        </section>

        <section style={{ ...glass, padding: 22, marginTop: 18 }}>
          <h2 style={h2}>You can also explore without knowing what to search for</h2>
          <div style={sub}>
            Use Discover when you just want to browse. Open any show to learn more, then favourite or rate the ones
            that match your taste so they can influence future recommendations.
          </div>
          <div style={actions}>
            <Link to="/discover" style={btnSecondary}>
              Explore Discover
            </Link>
            <Link to="/search" style={btnSecondary}>
              Search a show
            </Link>
          </div>
        </section>

        <section style={{ ...highlight, marginTop: 18 }}>
          <div style={{ ...titleSm, fontSize: 20 }}>Ready to start? Create an account, then add 5 shows you love.</div>
          <div style={{ ...text, maxWidth: 760 }}>
            Signing up only takes an email address and password. Once you’re in, start with a handful of strong
            favourites, add some ratings, then check your recommendations. You can refine your profile as you go.
          </div>
          <div style={actions}>
            <Link to="/login" style={btnPrimary}>
              Get started
            </Link>
            <Link to="/recs" style={btnSecondary}>
              View recommendations
            </Link>
          </div>
        </section>
      </div>
    </div>
  );
}

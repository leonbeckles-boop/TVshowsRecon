import React from "react";
import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";

export default function HowToUse() {
  // ----- Styles (matched to Wrapped/Profile glass format) -----
  const pageWrap: React.CSSProperties = {
    paddingTop: 120,
    paddingLeft: 16,
    paddingRight: 16,
    paddingBottom: 40,
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

  const h1: React.CSSProperties = { fontSize: 34, margin: 0 };
  const sub: React.CSSProperties = { opacity: 0.8, marginTop: 6 };

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
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
    gap: 14,
    marginTop: 16,
  };

  const card: React.CSSProperties = {
    ...glass,
    padding: 16,
  };

  const titleSm: React.CSSProperties = { fontSize: 16, margin: 0, fontWeight: 700 as any };
  const text: React.CSSProperties = { opacity: 0.8, marginTop: 8, lineHeight: 1.45 };
  const list: React.CSSProperties = { opacity: 0.78, marginTop: 10, paddingLeft: 18, lineHeight: 1.55 };

  const actions: React.CSSProperties = {
    display: "flex",
    flexWrap: "wrap",
    gap: 10,
    marginTop: 14,
  };

  const btnPrimary: React.CSSProperties = {
    ...pill,
    cursor: "pointer",
    textDecoration: "none",
    border: "1px solid rgba(56,189,248,0.35)",
    background: "rgba(56,189,248,0.18)",
    color: "rgba(240,250,255,0.95)",
    fontWeight: 700,
  };

  const btnSecondary: React.CSSProperties = {
    ...pill,
    cursor: "pointer",
    textDecoration: "none",
    color: "rgba(255,255,255,0.9)",
  };

  const stepBadge: React.CSSProperties = {
    width: 28,
    height: 28,
    borderRadius: 999,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 13,
    fontWeight: 800,
    border: "1px solid rgba(56,189,248,0.35)",
    background: "rgba(56,189,248,0.18)",
    color: "rgba(240,250,255,0.95)",
    flex: "0 0 auto",
  };

  return (
    <div>
      <PageHeader
        title="How to use WhatNext"
        subtitle="Add favourites + ratings to teach your taste — recommendations improve fast."
      />

      <div style={pageWrap}>
        <div style={{ ...pill, marginBottom: 10 }}>New here? Start in under 60 seconds ✅</div>

        <div style={{ ...glass, padding: 18 }}>
          <div style={h1}>Get better recs in 3 quick steps</div>
          <div style={sub}>
            WhatNext learns from the shows you save and rate. The more signal you give it, the smarter it gets.
          </div>

          <div style={grid3}>
            <div style={card}>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div style={stepBadge}>1</div>
                <div style={titleSm}>Search for shows you’ve watched</div>
              </div>
              <div style={text}>
                Go to <b>Search</b> and add a few shows you genuinely enjoyed. Start with your favourites — not just
                what’s popular.
              </div>
              <div style={actions}>
                <Link to="/search" style={btnPrimary}>
                  Go to Search
                </Link>
              </div>
            </div>

            <div style={card}>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div style={stepBadge}>2</div>
                <div style={titleSm}>Favourite + rate</div>
              </div>
              <div style={text}>
                Add shows to <b>Favourites</b> and give them a rating. Ratings help separate “love it” from “it’s okay”.
              </div>
              <ul style={list}>
                <li>Aim for <b>5 favourites</b> to start</li>
                <li>Add <b>5 ratings</b> for a big accuracy jump</li>
                <li>Use the <b>✕</b> hide button on shows you’d never watch</li>
              </ul>
              <div style={actions}>
                <Link to="/favorites" style={btnSecondary}>
                  View Favourites
                </Link>
              </div>
            </div>

            <div style={card}>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div style={stepBadge}>3</div>
                <div style={titleSm}>Check Recommendations</div>
              </div>
              <div style={text}>
                Head to <b>Recommendations</b> and refresh. As you add more favourites/ratings, results become sharper,
                newer, and more “you”.
              </div>
              <div style={actions}>
                <Link to="/recs" style={btnPrimary}>
                  View Recommendations
                </Link>
              </div>
            </div>
          </div>

          <div style={{ ...grid3, marginTop: 14 }}>
            <div style={card}>
              <div style={titleSm}>Best-results checklist</div>
              <ul style={list}>
                <li>Favourite shows you’d recommend to a friend</li>
                <li>Rate finished shows (even if you dropped them)</li>
                <li>Hide shows that are totally not your thing</li>
                <li>Come back after a few days — you’ll see new picks</li>
              </ul>
            </div>

            <div style={card}>
              <div style={titleSm}>WhatNext is doing under the hood</div>
              <ul style={list}>
                <li>Matches your favourites to similar shows</li>
                <li>Balances taste + quality</li>
                <li>Surfaces newer titles you may have missed</li>
                <li>Improves continuously as your library grows</li>
              </ul>
            </div>

            <div style={card}>
              <div style={titleSm}>Quick start target</div>
              <div style={text}>
                If you do one thing: add <b>5 favourites</b> and <b>5 ratings</b>.
              </div>
              <div style={{ ...pill, marginTop: 12, opacity: 0.85 }}>
                Tip: favourites = what you love • ratings = how much you love it
              </div>
            </div>
          </div>

          <div style={{ marginTop: 14, opacity: 0.65, fontSize: 12 }}>
            This page is here to help you get great results quickly. Once you’ve added a few shows, you can ignore it
            completely.
          </div>
        </div>
      </div>
    </div>
  );
}

import React from "react";
import { Routes, Route, useLocation } from "react-router-dom";
import PageHeader from "./components/PageHeader";

import Login from "./pages/login";
import Register from "./pages/register";
import Recs from "./pages/recs";
import Discover from "./pages/discover";
import Favorites from "./pages/favorites";
import Watchlist from "./pages/watchlist";
import Search from "./pages/search";
import Wrapped from "./pages/wrapped";
import ShowDetails from "./components/ShowDetails";
import AdminDashboard from "./pages/AdminDashboard";
import HowToUse from "./pages/HowToUse";
import ShowsLike from "./pages/ShowsLike";
import ShowsLikeHub from "./pages/ShowsLikeHub";
import BestShows from "./pages/BestShows";
import SEOIndex from "./pages/SEOIndex";
import { Navigate } from "react-router-dom";
import { useAuth } from "./auth/AuthProvider";



function getHeaderMeta(pathname: string) {

  if (pathname === "/discover") {
    return {
      title: "Discover",
      subtitle: "Discover new & trending shows to add to your library",
    };
  }

  if (pathname === "/search") {
    return {
      title: "Search",
      subtitle: "Search for shows to add to your library",
    };
  }

  if (pathname === "/favorites") {
    return {
      title: "Favourites",
      subtitle: "Your saved favourites",
    };
  }

  if (pathname === "/watchlist") {
    return {
      title: "Watchlist",
      subtitle: "Track what you are currently watching or want to watch next",
    };
  }

  if (pathname === "/recs") {
    return {
      title: "Recommendations",
      subtitle:
        "Personalised picks for you based on your favourite shows and ratings",
    };
  }

  if (pathname === "/wrapped") {
    return {
      title: "Profile",
      subtitle: "Your viewing profile and stats",
    };
  }

  if (pathname === "/HowToUse") {
    return {
      title: "How To Use",
      subtitle: "How WhatNext works",
    };
  }

  if (pathname.startsWith("/show/")) {
    return {
      title: "Show Details",
      subtitle: "More about this show",
    };
  }

  if (pathname === "/admin") {
    return {
      title: "Admin",
      subtitle: "Dashboard and app overview",
    };
  }

  if (pathname === "/shows-like") {
    return {
      title: "Shows Like",
      subtitle: "Browse similar shows by category",
    };
  }

  if (pathname.startsWith("/shows-like/")) {
    return {
      title: "Shows Like",
      subtitle: "Find similar shows to watch next",
    };
  }

  return {
    title: "Discover",
    subtitle: "Discover new & trending shows to add to your library",
  };
}


export default function App() {
  const location = useLocation();
  const { user } = useAuth();

  const hideHeader =
    location.pathname === "/login" || location.pathname === "/register";

  const headerMeta = getHeaderMeta(location.pathname);

  return (
    <div className="min-h-screen bg-[#020617] text-slate-100">
      {!hideHeader && (
        <PageHeader
          title={headerMeta.title}
          subtitle={headerMeta.subtitle}
        />
      )}

      <Routes>
        <Route path="/HowToUse" element={<HowToUse />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/discover" element={<Discover />} />
        <Route path="/search" element={<Search />} />
        <Route path="/favorites" element={<Favorites />} />
        <Route path="/watchlist" element={<Watchlist />} />
        <Route path="/recs" element={<Recs />} />
        <Route path="/wrapped" element={<Wrapped />} />
        <Route path="/show/:tmdb_id" element={<ShowDetails />} />
        <Route path="/admin" element={<AdminDashboard />} />

        {/* Shows Like pages */}
        <Route path="/shows-like" element={<ShowsLikeHub />} />
        <Route path="/shows-like/:slug" element={<ShowsLike />} />

        <Route
          path="/best-crime-tv-shows"
          element={
            <BestShows
              title="Best Crime TV Shows"
              intro="Looking for the best crime TV series ever made? These gripping dramas feature unforgettable characters, intense storytelling and some of the most acclaimed shows in television history."
              endpoint="/seo/best-crime"
            />
          }
        />

        <Route
          path="/best-drama-tv-shows"
          element={
            <BestShows
              title="Best Drama TV Shows"
              intro="Looking for the best drama TV series ever made? These critically acclaimed shows feature powerful storytelling, unforgettable characters and some of the most gripping television ever produced."
              endpoint="/seo/best-drama"
            />
          }
        />

        <Route
          path="/best-sci-fi-tv-series"
          element={
            <BestShows
              title="Best Sci-Fi TV Series"
              intro="From mind-bending mysteries to futuristic worlds, these are some of the best science fiction TV shows to watch if you love sci-fi storytelling."
              endpoint="/seo/best-scifi"
            />
          }
        />

        <Route
          path="/best-tv-shows-like-breaking-bad"
          element={
            <BestShows
              title="Best TV Shows Like Breaking Bad"
              intro="If you loved Breaking Bad, these shows deliver similar dark storytelling, anti-heroes and gripping drama."
              endpoint="/seo/best-like-breaking-bad"
            />
          }
        />

        <Route path="/seo-index" element={<SEOIndex />} />

       <Route
          path="/"
            element={user ? <Navigate to="/discover" replace /> : <Navigate to="/shows-like" replace />}
/>

      </Routes>

      <footer className="wn-footer">
        © {new Date().getFullYear()} WhatNextTV.org
        <br />
        Personalised TV recommendations
      </footer>
    </div>
  );
}
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
      subtitle: "Personalised picks for you based on your favourite shows and ratings",
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

  return {
    title: "Discover",
    subtitle: "Discover new & trending shows to add to your library",
  };
}

export default function App() {
  const location = useLocation();

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
        <Route path="*" element={<Discover />} />
      </Routes>

      <footer className="wn-footer">
        © {new Date().getFullYear()} WhatNextTV.org  
        <br />
        Personalised TV recommendations
      </footer>
    </div>
  );
}
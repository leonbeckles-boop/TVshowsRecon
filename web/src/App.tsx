import React from "react";
import { Routes, Route } from "react-router-dom";

import Login from "./pages/login";
import Register from "./pages/register";
import Recs from "./pages/recs";
import Discover from "./pages/discover";
import Favorites from "./pages/favorites";
import Watchlist from "./pages/watchlist";
import Search from "./pages/search";
import Wrapped from "./pages/wrapped"; 
import ShowDetails from "./components/ShowDetails";


import AdminDashboard from "./pages/AdminDashboard"; // ← NEW
import HowToUse from "./pages/HowToUse";

export default function App() {
  return (
    <div className="min-h-screen bg-[#020617] text-slate-100">
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

        {/* 👇 NEW ADMIN ROUTE */}
        <Route path="/admin" element={<AdminDashboard />} />

        {/* catch-all LAST */}
        <Route path="*" element={<Discover />} />
      </Routes>
    </div>
  );
}

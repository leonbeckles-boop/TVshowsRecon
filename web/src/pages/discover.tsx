import React, { useEffect, useState, useMemo, useCallback } from "react";
import PageHeader from "../components/PageHeader";
import ShowCard from "../components/ShowCard";
import {
  getDiscover,
  listFavoriteShows,
  addFavorite,
  removeFavorite,
  markNotInterested,
  type Show,
} from "../api";
import OnboardingModal from "../components/OnboardingModal";
import { useAuth } from "../auth/AuthProvider";
import "./discover.css";

/* ----------------- helpers ----------------- */

function getTmdbId(any: any): number | null {
  const cand = any?.tmdb_id ?? any?.external_id ?? any?.id ?? any?.show_id;
  const n = Number(cand);
  return Number.isFinite(n) && n > 0 ? n : null;
}

const SECTION_TITLES = [
  "Top Featured",
  "New & Trending",
  "Top Shows of the Decade",
  "Top Drama",
  "Top Crime",
  "Top Thriller",
];

/* --------- skeletons for perceived speed --------- */

function DiscoverSkeletonSection({ title }: { title: string }) {
  return (
    <section className="mt-8">
      <h2
        className="text-2xl md:text-3xl font-bold mb-2"
        style={{ color: "#ffffff" }}
      >
        {title}
      </h2>

      <p
        className="max-w-2xl text-xs sm:text-sm md:text-base mb-4"
        style={{ color: "#e5e7eb" }}
      >
        <span className="inline-block h-4 w-64 rounded bg-slate-700/60 animate-pulse" />
      </p>

      <div className="discover-grid">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="aspect-[2/3] rounded-xl bg-slate-800/70 animate-pulse"
          />
        ))}
      </div>
    </section>
  );
}

/* ----------------- main component ----------------- */

export default function DiscoverPage() {
  const { user } = useAuth();
  const userId = user?.id ?? null;

  const [sections, setSections] = useState<
    { title: string; items: Show[] }[]
  >([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [showOnboarding, setShowOnboarding] = useState(false);

  const [favorites, setFavorites] = useState<Show[]>([]);

  /* ---- onboarding once per user ---- */

  useEffect(() => {
    if (!user) return;

    try {
      const key = `wn_onboarding_seen_${user.id ?? "guest"}`;
      const alreadySeen = window.localStorage.getItem(key);

      if (!alreadySeen) {
        setShowOnboarding(true);
        window.localStorage.setItem(key, "1");
      }
    } catch (err) {
      console.error("Error checking onboarding flag:", err);
    }
  }, [user]);

  /* ---- load discover sections ---- */

  useEffect(() => {
    let isMounted = true;

    async function run() {
      setLoading(true);
      const t0 = performance.now();
      try {
        const response = await getDiscover();
        const t1 = performance.now();
        console.log(
          `[Discover] getDiscover() took ${(t1 - t0).toFixed(0)} ms`
        );

        if (!isMounted) return;

        if (response && typeof response === "object") {
          const newSections: { title: string; items: Show[] }[] = [];

          const tryAdd = (title: string, arr?: any[]) => {
            if (Array.isArray(arr) && arr.length > 0) {
              newSections.push({ title, items: arr as Show[] });
            }
          };

          tryAdd("Top Featured", response.featured);
          tryAdd("New & Trending", response.trending);
          tryAdd("Top Shows of the Decade", response.top_decade);
          tryAdd("Top Drama", response.drama);
          tryAdd("Top Crime", response.crime);
          tryAdd("Top Thriller", response.thriller);

          setSections(newSections);
        }
      } catch (err) {
        console.error("Error in getDiscover:", err);
      } finally {
        if (isMounted) setLoading(false);
      }
    }

    void run();
    return () => {
      isMounted = false;
    };
  }, []);

  /* ---- load favourites ---- */

  useEffect(() => {
    if (!userId) return;

    const loadFavorites = async () => {
      const t0 = performance.now();
      try {
        const favs = await listFavoriteShows(userId);
        const t1 = performance.now();
        console.log(
          `[Discover] listFavoriteShows(${userId}) took ${(t1 - t0).toFixed(
            0,
          )} ms`
        );
        setFavorites(favs ?? []);
      } catch (e) {
        console.error("Failed to load favorites for Discover", e);
      }
    };

    void loadFavorites();
  }, [userId]);

  const favSet = useMemo(() => {
    const set = new Set<number>();
    for (const f of favorites) {
      const id = getTmdbId(f);
      if (id) set.add(id);
    }
    return set;
  }, [favorites]);

  /* ---- handlers ---- */

  const handleToggleFav = useCallback(
    async (show: any) => {
      if (!userId) return;
      const tmdbId = getTmdbId(show);
      if (!tmdbId) return;

      const isCurrentlyFav = favSet.has(tmdbId);
      try {
        if (isCurrentlyFav) {
          await removeFavorite(userId, tmdbId);
          setFavorites((prev) => prev.filter((s) => getTmdbId(s) !== tmdbId));
        } else {
          await addFavorite(userId, tmdbId);
          setFavorites((prev) => [...prev, show as Show]);
        }
      } catch (e) {
        console.error("Failed to toggle favourite (Discover)", e);
      }
    },
    [userId, favSet],
  );

  const handleHide = useCallback(
    async (show: any) => {
      if (!userId) return;
      const tmdbId = getTmdbId(show);
      if (!tmdbId) return;

      // Optimistically remove from all sections
      setSections((prev) =>
        prev.map((section) => ({
          ...section,
          items: section.items.filter((s) => getTmdbId(s) !== tmdbId),
        })),
      );

      try {
        await markNotInterested(userId, tmdbId);
      } catch (e) {
        console.error("Failed to mark not interested (Discover)", e);
      }
    },
    [userId],
  );

  /* ---- render helpers ---- */

  const renderSection = (title: string, items: Show[]) => {
    if (!items || items.length === 0) return null;

    return (
      <section key={title} className="mt-8">
        <h2
          className="text-2xl md:text-3xl font-bold mb-2"
          style={{ color: "#ffffff" }}
        >
          {title}
        </h2>

        <p
          className="max-w-2xl text-xs sm:text-sm md:text-base mb-4"
          style={{ color: "#e5e7eb" }}
        >
          Curated highlights across genres—handpicked, not based on your
          favourites.
        </p>

        <div className="discover-grid">
          {items.map((show) => {
            const tmdbId = getTmdbId(show) ?? undefined;
            const key = String(
              tmdbId ??
                (show as any).id ??
                (show as any).external_id ??
                Math.random(),
            );
            const isFav = tmdbId ? favSet.has(tmdbId) : false;

            return (
              <ShowCard
                key={key}
                show={show}
                isFav={isFav}
                onToggleFav={userId ? () => handleToggleFav(show) : undefined}
                onHide={userId ? () => handleHide(show) : undefined}
              />
            );
          })}
        </div>
      </section>
    );
  };

  const hasRealSections = sections.length > 0;

  /* ---- render ---- */

  return (
    <div className="pb-10">
      <PageHeader
        title="Discover"
        subtitle="Explore highly rated TV from the last decade, plus trending picks across genres. These are global suggestions, not based on your favourites."
        centered
      />

       <div
        className="max-w-screen-2xl mx-auto px-3 sm:px-4 md:px-8"
        style={{ paddingTop: "150px" }}
        >

        {loading && !hasRealSections ? (
          <>
            {SECTION_TITLES.map((title) => (
              <DiscoverSkeletonSection key={title} title={title} />
            ))}
          </>
        ) : (
          sections.map((s) => renderSection(s.title, s.items))
        )}
      </div>

      <OnboardingModal
        open={showOnboarding}
        onClose={() => setShowOnboarding(false)}
      />
    </div>
  );
}

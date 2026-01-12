import { useEffect, useMemo, useState } from "react";
import { listRatings, type UserRating } from "../api";

export type RatingsMap = Record<number, number>; // tmdb_id -> rating

export function useRatings(userId?: number | null) {
  const [ratings, setRatings] = useState<UserRating[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    if (!userId) {
      setRatings([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await listRatings(userId);
      setRatings(data);
    } catch (e: any) {
      setError(e?.message || "Failed to load ratings");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const ratingsMap: RatingsMap = useMemo(() => {
    const m: RatingsMap = {};
    for (const r of ratings) {
      if (typeof r.tmdb_id === "number" && typeof r.rating === "number") {
        m[r.tmdb_id] = r.rating;
      }
    }
    return m;
  }, [ratings]);

  return { ratings, ratingsMap, loading, error, refresh };
}

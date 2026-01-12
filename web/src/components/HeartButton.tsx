import { useState } from "react";
import { addFavorite, removeFavorite } from "../api";

type Props = {
  userId: number;
  tmdbId?: number | null;         // TMDb id (required to toggle)
  isFavorite?: boolean;           // initial state
  size?: number;                  // px
  onChange?: (fav: boolean) => void;
};

export default function HeartButton({ userId, tmdbId, isFavorite, size = 22, onChange }: Props) {
  const [fav, setFav] = useState<boolean>(!!isFavorite);
  const [busy, setBusy] = useState(false);

  const canToggle = !!tmdbId && userId > 0;

  async function toggle() {
    if (!canToggle || busy) return;
    setBusy(true);
    try {
      if (fav) {
        await removeFavorite(userId, tmdbId!);
        setFav(false);
        onChange?.(false);
      } else {
        await addFavorite(userId, tmdbId!);
        setFav(true);
        onChange?.(true);
      }
    } catch (e) {
      console.error("favorite toggle failed", e);
      // optional: surface a toast here
    } finally {
      setBusy(false);
    }
  }

  const label = fav ? "Remove from favorites" : "Add to favorites";

  return (
    <button
      onClick={toggle}
      disabled={!canToggle || busy}
      title={!canToggle ? "Sign in to use favorites" : label}
      aria-label={label}
      style={{
        width: size,
        height: size,
        lineHeight: `${size}px`,
        fontSize: size * 0.9,
        border: "none",
        background: "transparent",
        cursor: canToggle && !busy ? "pointer" : "default",
        opacity: busy ? 0.6 : 1,
        color: fav ? "#e0245e" : "#888",
        padding: 0,
      }}
    >
      {fav ? "♥" : "♡"}
    </button>
  );
}

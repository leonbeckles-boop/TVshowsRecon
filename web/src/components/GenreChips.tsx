import * as React from "react";

type Chip = { id: string; label: string };

// Adjust to match your available genres/slugs
export const GENRES: Chip[] = [
  { id: "crime", label: "Crime" },
  { id: "scifi", label: "Sci-Fi" },
  { id: "drama", label: "Drama" },
  { id: "comedy", label: "Comedy" },
  { id: "fantasy", label: "Fantasy" },
];

export default function GenreChips({
  initialSelected = [],
  onChange,
}: {
  initialSelected?: string[];
  onChange?: (ids: string[]) => void;
}) {
  const [sel, setSel] = React.useState<string[]>(() => {
    if (typeof window === "undefined") return initialSelected;
    const url = new URL(window.location.href);
    const fromUrl = (url.searchParams.get("genres") || "")
      .split(",")
      .filter(Boolean);
    return fromUrl.length ? fromUrl : initialSelected;
  });

  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (sel.length) url.searchParams.set("genres", sel.join(","));
    else url.searchParams.delete("genres");
    window.history.replaceState({}, "", url.toString());
    onChange?.(sel);
  }, [sel, onChange]);

  return (
    <div className="flex flex-wrap gap-2">
      {GENRES.map((g) => {
        const active = sel.includes(g.id);
        return (
          <button
            key={g.id}
            type="button"
            aria-pressed={active}
            onClick={() =>
              setSel((prev) =>
                prev.includes(g.id)
                  ? prev.filter((x) => x !== g.id)
                  : [...prev, g.id]
              )
            }
            className={[
              "inline-flex items-center rounded-full px-3.5 py-1.5 text-[11px] font-semibold tracking-wide transition-all duration-200",
              active
                ? "bg-sky-400 text-slate-950 shadow-[0_0_18px_rgba(56,189,248,0.85)] border border-sky-300"
                : "bg-slate-900/80 text-slate-200 border border-slate-600 hover:border-sky-400/80 hover:bg-slate-800/90",
            ].join(" ")}
          >
            {g.label}
          </button>
        );
      })}
    </div>
  );
}

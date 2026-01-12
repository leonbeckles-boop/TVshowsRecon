import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listRatings, upsertRating, type UserRating } from "../api";
import { useAuth } from "../auth/AuthProvider";

type Draft = {
  tmdb_id: number;
  rating: number;
  title?: string | null;
  seasons_completed?: number | null;
  notes?: string | null;
};

type SavePayload = {
  tmdb_id: number;
  rating: number;
  title?: string;
  seasons_completed?: number | null;
  notes?: string;
};

function numberOrNull(v: string): number | null {
  if (v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function Row({
  r,
  onSaved,
}: {
  r: UserRating;
  onSaved: (saved: SavePayload) => Promise<void> | void;
}) {
  const [draft, setDraft] = useState<Draft>({
    tmdb_id: r.tmdb_id,
    rating: r.rating,
    title: r.title ?? "",
    seasons_completed: r.seasons_completed ?? null,
    notes: r.notes ?? "",
  });
  const [busy, setBusy] = useState(false);

  const dirty =
    draft.rating !== r.rating ||
    (draft.title ?? "") !== (r.title ?? "") ||
    (draft.seasons_completed ?? null) !== (r.seasons_completed ?? null) ||
    (draft.notes ?? "") !== (r.notes ?? "");

  async function save() {
    if (busy || !dirty) return;
    setBusy(true);
    try {
      const payload: SavePayload = {
        tmdb_id: draft.tmdb_id,
        rating: draft.rating,
        title: draft.title ?? undefined,
        seasons_completed: draft.seasons_completed ?? undefined,
        notes: draft.notes ?? undefined,
      };
      await onSaved(payload);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        border: "1px solid #eee",
        borderRadius: 10,
        padding: 12,
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: 12,
        background: "#fff",
      }}
      onKeyDown={(e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
          e.preventDefault();
          void save();
        }
      }}
    >
      <div style={{ display: "grid", gap: 8 }}>
        <div style={{ fontWeight: 600 }}>
          {r.title || "(untitled)"}{" "}
          <span style={{ color: "#777", fontWeight: 400 }}>TMDb: {r.tmdb_id}</span>
        </div>

        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <label>
            <span style={{ fontSize: 12, color: "#555" }}>Rating (0–10)</span>
            <input
              type="number"
              min={0}
              max={10}
              step={0.5}
              value={draft.rating}
              onChange={(e) => setDraft((d) => ({ ...d, rating: Number(e.currentTarget.value) }))}
              style={{ width: 90, marginLeft: 8, padding: "6px 8px", border: "1px solid #ddd", borderRadius: 8 }}
            />
          </label>

          <label>
            <span style={{ fontSize: 12, color: "#555" }}>Seasons completed</span>
            <input
              type="number"
              min={0}
              value={draft.seasons_completed ?? ""}
              onChange={(e) =>
                setDraft((d) => ({ ...d, seasons_completed: numberOrNull(e.currentTarget.value) }))
              }
              style={{ width: 110, marginLeft: 8, padding: "6px 8px", border: "1px solid #ddd", borderRadius: 8 }}
            />
          </label>

          <label style={{ flex: 1, minWidth: 220 }}>
            <span style={{ fontSize: 12, color: "#555" }}>Title (optional)</span>
            <input
              type="text"
              value={draft.title ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, title: e.currentTarget.value }))}
              placeholder="Show title override"
              style={{ width: "100%", marginLeft: 8, padding: "6px 8px", border: "1px solid #ddd", borderRadius: 8 }}
            />
          </label>
        </div>

        <label>
          <span style={{ fontSize: 12, color: "#555" }}>Notes</span>
          <textarea
            rows={2}
            maxLength={2000}
            value={draft.notes ?? ""}
            onChange={(e) => setDraft((d) => ({ ...d, notes: e.currentTarget.value }))}
            placeholder="Why you rated it this way…"
            style={{ width: "100%", marginTop: 4, padding: "8px 10px", border: "1px solid #ddd", borderRadius: 8 }}
          />
        </label>
      </div>

      <div style={{ display: "grid", alignContent: "start" }}>
        <button
          onClick={() => void save()}
          disabled={!dirty || busy}
          style={{
            padding: "8px 12px",
            borderRadius: 8,
            border: "none",
            background: !dirty || busy ? "#bbb" : "#111",
            color: "#fff",
            cursor: !dirty || busy ? "default" : "pointer",
            height: 36,
          }}
          title={!dirty ? "No changes" : "Save rating"}
        >
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}

export default function RatingsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const userId = user?.id ?? 0;

  const [items, setItems] = useState<UserRating[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // Add-new form
  const [newTmdb, setNewTmdb] = useState<string>("");
  const [newRating, setNewRating] = useState<string>("");
  const [newTitle, setNewTitle] = useState<string>("");
  const [newNotes, setNewNotes] = useState<string>("");
  const [busyAdd, setBusyAdd] = useState(false);

  useEffect(() => {
    let alive = true;
    async function run() {
      if (!userId) {
        navigate("/login");
        return;
      }
      setLoading(true);
      setErr(null);
      try {
        const data = await listRatings(userId);
        if (!alive) return;
        setItems(data ?? []);
      } catch (e: any) {
        if (!alive) return;
        setErr(e?.message || "Failed to load ratings");
        setItems([]);
      } finally {
        if (alive) setLoading(false);
      }
    }
    void run();
    return () => {
      alive = false;
    };
  }, [userId, navigate]);

  async function saveRow(d: SavePayload) {
    if (!userId) return;
    await upsertRating(userId, {
  tmdb_id: d.tmdb_id,
  rating: d.rating,
  title: d.title ?? undefined,
  seasons_completed: d.seasons_completed ?? undefined,
  notes: d.notes ?? undefined,
});
    setItems((prev) => {
      const idx = prev.findIndex((p) => p.tmdb_id === d.tmdb_id);
      const merged: UserRating = { tmdb_id: d.tmdb_id,
        rating: d.rating,
        title: d.title,
        seasons_completed: d.seasons_completed ?? undefined,
        notes: d.notes,
      };
      const next = [...prev];
      if (idx >= 0) next[idx] = { ...next[idx], ...merged };
      else next.unshift(merged);
      return next;
    });
  }

  const canAdd =
    Number.isFinite(Number(newTmdb)) &&
    Number(newTmdb) > 0 &&
    Number.isFinite(Number(newRating)) &&
    Number(newRating) >= 0 &&
    Number(newRating) <= 10;

  async function addNew() {
    if (!userId || !canAdd) return;
    const tmdb_id = Number(newTmdb);
    const rating = Number(newRating);
    setBusyAdd(true);
    try {
      await upsertRating(userId, {
  tmdb_id,
  rating,
  title: newTitle || undefined,
  notes: newNotes || undefined,
});
      setItems((prev) => [
        { tmdb_id,
          rating,
          title: newTitle || undefined,
          seasons_completed: undefined,
          notes: newNotes || undefined,
        },
        ...prev.filter((p) => p.tmdb_id !== tmdb_id),
      ]);
      setNewTmdb("");
      setNewRating("");
      setNewTitle("");
      setNewNotes("");
    } catch (e: any) {
      alert(e?.message || "Failed to add rating");
    } finally {
      setBusyAdd(false);
    }
  }

  const header = useMemo(
    () => (
      <div style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Your ratings</h2>
        <div style={{ color: "#666", fontSize: 14 }}>View and edit the shows you’ve rated.</div>
      </div>
    ),
    []
  );

  if (loading) return <div style={{ padding: 16 }}>Loading…</div>;
  if (err) return <div style={{ padding: 16, color: "#b00020" }}>{err}</div>;

  return (
    <div style={{ padding: 8, display: "grid", gap: 16 }}>
      {header}

      {/* Add new rating (by TMDb ID) */}
      <div
        style={{
          border: "1px solid #eee",
          borderRadius: 10,
          padding: 12,
          display: "grid",
          gap: 8,
          background: "#fff",
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 4 }}>Add a rating</div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <label>
            <span style={{ fontSize: 12, color: "#555" }}>TMDb ID</span>
            <input
              type="number"
              min={1}
              value={newTmdb}
              onChange={(e) => setNewTmdb(e.currentTarget.value)}
              style={{ width: 120, marginLeft: 8, padding: "6px 8px", border: "1px solid #ddd", borderRadius: 8 }}
            />
          </label>
          <label>
            <span style={{ fontSize: 12, color: "#555" }}>Rating (0–10)</span>
            <input
              type="number"
              min={0}
              max={10}
              step={0.5}
              value={newRating}
              onChange={(e) => setNewRating(e.currentTarget.value)}
              style={{ width: 100, marginLeft: 8, padding: "6px 8px", border: "1px solid #ddd", borderRadius: 8 }}
            />
          </label>
          <label style={{ flex: 1, minWidth: 180 }}>
            <span style={{ fontSize: 12, color: "#555" }}>Title (optional)</span>
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.currentTarget.value)}
              placeholder="Show title"
              style={{ width: "100%", marginLeft: 8, padding: "6px 8px", border: "1px solid #ddd", borderRadius: 8 }}
            />
          </label>
        </div>
        <label>
          <span style={{ fontSize: 12, color: "#555" }}>Notes</span>
          <textarea
            rows={2}
            maxLength={2000}
            value={newNotes}
            onChange={(e) => setNewNotes(e.currentTarget.value)}
            placeholder="Optional notes…"
            style={{ width: "100%", marginTop: 4, padding: "8px 10px", border: "1px solid #ddd", borderRadius: 8 }}
          />
        </label>
        <div>
          <button
            onClick={() => void addNew()}
            disabled={busyAdd || !canAdd}
            style={{
              padding: "8px 12px",
              borderRadius: 8,
              border: "none",
              background: busyAdd || !canAdd ? "#bbb" : "#111",
              color: "#fff",
              cursor: busyAdd || !canAdd ? "default" : "pointer",
            }}
            title={!canAdd ? "Enter a TMDb ID (>0) and a rating between 0–10" : "Add rating"}
          >
            {busyAdd ? "Adding…" : "Add rating"}
          </button>
        </div>
      </div>

      {/* Existing ratings */}
      {!items.length ? (
        <div style={{ color: "#666" }}>You haven’t rated any shows yet.</div>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {items.map((r) => (
            <Row key={r.tmdb_id} r={r} onSaved={saveRow} />
          ))}
        </div>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import { StarRow } from "./stars";

export function RatingModal({
  open,
  title,
  initial,
  onSave,
  onClose,
}: {
  open: boolean;
  title?: string;
  initial?: number;
  onSave: (val: number) => Promise<void> | void;
  onClose: () => void;
}) {
  const [val, setVal] = useState<number>(initial ?? 0);
  useEffect(() => setVal(initial ?? 0), [initial, open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      {/* Modal */}
      <div className="absolute inset-0 flex items-center justify-center p-4">
        <div className="w-full max-w-md rounded-2xl bg-white shadow-xl border border-slate-200">
          <div className="px-5 py-4 border-b">
            <div className="text-lg font-semibold">Rate this show</div>
            {title && <div className="text-slate-600 text-sm mt-0.5">{title}</div>}
          </div>
          <div className="p-5 space-y-4">
            <div className="flex items-center justify-between">
              <StarRow value={val} interactive onChange={setVal} />
              <div className="text-sm text-slate-600">★ {val.toFixed(1)} / 10</div>
            </div>
            <input
              type="range"
              min={0}
              max={10}
              step={0.1}
              value={val}
              onChange={(e) => setVal(parseFloat(e.target.value))}
              className="w-full"
            />
          </div>
          <div className="px-5 py-4 border-t flex justify-end gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-sm rounded-lg border border-slate-300 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              onClick={() => onSave(val)}
              className="px-3 py-1.5 text-sm rounded-lg bg-emerald-600 text-white hover:bg-emerald-700"
            >
              Save Rating
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

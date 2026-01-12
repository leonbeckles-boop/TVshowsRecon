import { useMemo } from "react";

type StarProps = {
  filled: number; // 0..1
  size?: number;
};

function Star({ filled, size = 18 }: StarProps) {
  // draw base star and overlay a filled mask for partials
  return (
    <div className="relative inline-block" style={{ width: size, height: size }}>
      <svg viewBox="0 0 24 24" className="absolute inset-0 text-slate-300" aria-hidden>
        <path
          fill="currentColor"
          d="M12 17.3l6.18 3.73-1.64-7.03L21 9.24l-7.19-.62L12 2 10.19 8.62 3 9.24l4.46 4.76L5.82 21z"
        />
      </svg>
      <div className="absolute inset-0 overflow-hidden" style={{ width: `${Math.max(0, Math.min(1, filled)) * 100}%` }}>
        <svg viewBox="0 0 24 24" className="text-amber-400" aria-hidden>
          <path
            fill="currentColor"
            d="M12 17.3l6.18 3.73-1.64-7.03L21 9.24l-7.19-.62L12 2 10.19 8.62 3 9.24l4.46 4.76L5.82 21z"
          />
        </svg>
      </div>
    </div>
  );
}

export function StarRow({
  value, // 0..10
  max = 10,
  interactive = false,
  onChange,
  size = 18,
}: {
  value: number;
  max?: number;
  interactive?: boolean;
  onChange?: (v: number) => void;
  size?: number;
}) {
  // map to 5 stars by halves (value/2)
  const fiveScale = Math.max(0, Math.min(max, value)) / (max / 5);
  const stars = useMemo(() => {
    return Array.from({ length: 5 }, (_, i) => {
      const start = i;
      const frac = Math.max(0, Math.min(1, fiveScale - start));
      return <Star key={i} filled={frac} size={size} />;
    });
  }, [fiveScale, size]);

  if (!interactive) return <div className="inline-flex items-center gap-1">{stars}</div>;

  // interactive: click position sets new value
  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!onChange) return;
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    const newFive = Math.max(0, Math.min(5, ratio * 5));
    const newValue = Math.round((newFive * (max / 5)) * 2) / 2; // step 0.5
    onChange(newValue);
  };

  return (
    <div className="inline-flex items-center gap-1 cursor-pointer select-none" onClick={handleClick} title={`${value.toFixed(1)}/${max}`}>
      {stars}
    </div>
  );
}
export default function Stars(props: {
  value: number;     // 0..10
  readOnly?: boolean;
  max?: number;
  size?: number;
  onChange?: (v: number) => void;
}) {
  const { readOnly = true, ...rest } = props;
  return <StarRow {...rest} interactive={!readOnly} />;
}
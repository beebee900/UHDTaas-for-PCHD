type Props = { t: number[]; mean: number[]; lower: number[]; upper: number[]; label: string };

const W = 640;
const H = 220;
const PAD = 28;

export function ForecastChart({ t, mean, lower, upper, label }: Props) {
  if (t.length < 2) return null;
  const lo = Math.min(...lower, ...mean);
  const hi = Math.max(...upper, ...mean);
  const span = hi - lo || 1;
  const x = (i: number) => PAD + ((t[i] - t[0]) / (t[t.length - 1] - t[0] || 1)) * (W - 2 * PAD);
  const y = (v: number) => H - PAD - ((v - lo) / span) * (H - 2 * PAD);
  const line = (values: number[]) => values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const band = `${line(upper)} ${[...lower].reverse().map((v, i) => `${x(lower.length - 1 - i)},${y(v)}`).join(" ")}`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} style={{ width: "100%", maxWidth: W }}>
      <polygon points={band} fill="currentColor" opacity={0.12} />
      <polyline points={line(mean)} fill="none" stroke="currentColor" strokeWidth={2} />
    </svg>
  );
}

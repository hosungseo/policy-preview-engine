import { pct } from "@/lib/format";

export interface MiniSeries { label: string; color: string; values: (number | null)[]; width?: number }

// One small chart: a few series over the measures (evenly spaced), shared y range passed in so charts compare.
export default function MiniLines({ title, sub, series, shorts, domain, foot }: {
  title: string; sub?: string; series: MiniSeries[]; shorts: string[]; domain: [number, number]; foot?: string;
}) {
  const W = 220, H = 110, l = 6, r = 6, t = 8, b = 10;
  const [lo, hi] = domain;
  const x = (i: number) => l + (i / Math.max(1, shorts.length - 1)) * (W - l - r);
  const y = (v: number) => t + ((hi - v) / Math.max(0.01, hi - lo)) * (H - t - b);
  const path = (vals: (number | null)[]) => {
    let d = "", pen = false;
    vals.forEach((v, i) => { if (v === null) { pen = false; return; } d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)} `; pen = true; });
    return d.trim();
  };
  return (
    <div className="pp-series-mini">
      <div className="pp-series-mini-head"><b>{title}</b>{sub && <span>{sub}</span>}</div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`${title} 흐름`}>
        {series.map((s) => (
          <g key={s.label}>
            <path d={path(s.values)} fill="none" stroke={s.color} strokeWidth={s.width ?? 2} strokeLinejoin="round" />
            {s.values.map((v, i) => v === null ? null : (
              <circle key={i} cx={x(i)} cy={y(v)} r="2.5" fill={s.color}><title>{`${shorts[i]} · ${s.label} ${pct(v)}`}</title></circle>
            ))}
          </g>
        ))}
      </svg>
      {foot && <div className="pp-series-mini-foot">{foot}</div>}
    </div>
  );
}

export function sharedDomain(values: (number | null)[]): [number, number] {
  const v = values.filter((x): x is number => x !== null);
  return [Math.max(0, Math.floor(Math.min(...v) * 10) / 10), Math.min(1, Math.ceil(Math.max(...v) * 10) / 10)];
}

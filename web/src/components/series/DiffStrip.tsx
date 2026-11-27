import { ppoint } from "@/lib/format";
import type { SeriesMeasure } from "@/lib/seriesTypes";
import { dims, xScale } from "./scale";

const INK = "#1e2124", INK2 = "#464c53", INK3 = "#6d7882", GRID = "#e6e8ea", AXIS = "#b1b8be";

function Strip({ measures, wide }: { measures: SeriesMeasure[]; wide: boolean }) {
  const { W, l, r } = dims(wide);
  const H = 140, top = 18, bottom = 22;
  const x = xScale(measures.map((m) => m.date), wide);
  const eff = measures.map((m) => m.effect.overall);
  const lows = eff.map((e) => (e.ci95 ? e.ci95[0] : e.diff)), highs = eff.map((e) => (e.ci95 ? e.ci95[1] : e.diff));
  const lo = Math.min(-0.02, ...lows) - 0.01, hi = Math.max(0.02, ...highs) + 0.01;
  const y = (v: number) => top + ((hi - v) / (hi - lo)) * (H - top - bottom);
  const step = hi - lo > 0.12 ? 0.05 : 0.02;
  const ticks: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(Math.round(v * 100) / 100);
  const bw = wide ? 16 : 10;
  const CLOSE = 44;
  const anchor = (i: number): { x: number; a: "start" | "middle" | "end" } => {
    const cx = x(i);
    if (i + 1 < measures.length && x(i + 1) - cx < CLOSE) return { x: cx + 3, a: "end" };
    if (i > 0 && cx - x(i - 1) < CLOSE) return { x: cx - 3, a: "start" };
    return { x: cx, a: "middle" };
  };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="대책별 누적 효과(퍼센트포인트)">
      {ticks.map((v) => (
        <g key={v}>
          <line x1={l} x2={W - r} y1={y(v)} y2={y(v)} stroke={v === 0 ? AXIS : GRID} />
          <text x={l - 6} y={y(v) + 4} textAnchor="end" fontSize="11.5" fill={INK3}>{ppoint(v, 0)}</text>
        </g>
      ))}
      {measures.map((m, i) => {
        const e = m.effect.overall, cx = x(i), y0 = y(0), y1 = y(e.diff);
        const color = e.diff < -0.005 ? "#e0858c" : e.diff > 0.005 ? "#86aff9" : "#cdd1d5";
        const h = Math.max(2, Math.abs(y1 - y0)), rr = Math.min(4, h / 2);
        const d = e.diff < 0
          ? `M${cx - bw / 2} ${y0} H${cx + bw / 2} V${y0 + h - rr} Q${cx + bw / 2} ${y0 + h} ${cx + bw / 2 - rr} ${y0 + h} H${cx - bw / 2 + rr} Q${cx - bw / 2} ${y0 + h} ${cx - bw / 2} ${y0 + h - rr} Z`
          : `M${cx - bw / 2} ${y0} H${cx + bw / 2} V${y0 - h + rr} Q${cx + bw / 2} ${y0 - h} ${cx + bw / 2 - rr} ${y0 - h} H${cx - bw / 2 + rr} Q${cx - bw / 2} ${y0 - h} ${cx - bw / 2} ${y0 - h + rr} Z`;
        const lo95 = e.ci95 ? e.ci95[0] : e.diff, hi95 = e.ci95 ? e.ci95[1] : e.diff;
        return (
          <g key={m.id}>
            <path d={d} fill={color}><title>{`${m.short} ${m.title}: 누적 효과 ${ppoint(e.diff)}%p`}</title></path>
            {i > 0 && <line x1={cx} x2={cx} y1={y(lo95)} y2={y(hi95)} stroke={INK2} />}
            <text x={anchor(i).x} y={e.diff < 0 ? y(lo95) + 13 : y(hi95) - 5} textAnchor={anchor(i).a} fontSize="11.5" fill={INK}>{ppoint(e.diff)}</text>
          </g>
        );
      })}
    </svg>
  );
}

export default function DiffStrip({ measures }: { measures: SeriesMeasure[] }) {
  return (
    <div className="pp-series-chart">
      <div className="pp-wide-only"><Strip measures={measures} wide /></div>
      <div className="pp-narrow-only"><Strip measures={measures} wide={false} /></div>
    </div>
  );
}

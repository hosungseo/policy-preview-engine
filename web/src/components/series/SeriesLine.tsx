import { SERIES_COLOR } from "@/lib/colors";
import { pct } from "@/lib/format";
import type { SeriesMeasure } from "@/lib/seriesTypes";
import { DAY, dims, quarterTicks, xScale } from "./scale";

const INK = "#1e2124", INK3 = "#6d7882", GRID = "#e6e8ea", AXIS = "#b1b8be";

export function favorDomain(measures: SeriesMeasure[]): [number, number] {
  const v = measures.flatMap((m) => [m.conditions.alone.favor, m.conditions.context.favor]);
  return [Math.max(0, Math.floor(Math.min(...v) * 10 - 0.5) / 10), Math.min(1, Math.ceil(Math.max(...v) * 10 + 0.5) / 10)];
}

function Chart({ measures, wide }: { measures: SeriesMeasure[]; wide: boolean }) {
  const { W, l, r } = dims(wide);
  const H = wide ? 330 : 260, top = 16, bottom = wide ? 58 : 30;
  const [lo, hi] = favorDomain(measures);
  const dates = measures.map((m) => m.date);
  const x = xScale(dates, wide);
  const y = (v: number) => top + ((hi - v) / (hi - lo)) * (H - top - bottom);
  const ticks: number[] = [];
  for (let v = lo; v <= hi + 1e-9; v += 0.1) ticks.push(Math.round(v * 10) / 10);
  const path = (k: "alone" | "context") =>
    measures.map((m, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(m.conditions[k].favor).toFixed(1)}`).join(" ");
  let lastX = -1e9, row = 0;
  const labels = measures.map((m, i) => { const px = x(i); row = px - lastX < 46 ? 1 - row : 0; lastX = px; return { px, row }; });
  const last = measures[measures.length - 1], li = measures.length - 1;
  let ya = y(last.conditions.alone.favor), yc = y(last.conditions.context.favor);
  if (Math.abs(ya - yc) < 16) {
    const mid = (ya + yc) / 2, up = last.conditions.alone.favor >= last.conditions.context.favor;
    ya = mid + (up ? -9 : 9); yc = mid + (up ? 9 : -9);
  }
  const low = measures.reduce((b, m, i) => (m.conditions.alone.favor < measures[b].conditions.alone.favor ? i : b), 0);
  const t0 = Date.parse(dates[0]) - 20 * DAY;
  const t1 = Date.parse(dates[dates.length - 1]) + 25 * DAY;
  const xDate = (d: string) => l + ((Date.parse(d) - t0) / (t1 - t0)) * (W - l - r);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="대책별 찬성 쪽 비율, 대책만과 누적 맥락">
      {ticks.map((v) => (
        <g key={v}>
          <line x1={l} x2={W - r} y1={y(v)} y2={y(v)} stroke={GRID} />
          <text x={l - 6} y={y(v) + 4} textAnchor="end" fontSize="11.5" fill={INK3}>{Math.round(v * 100)}%</text>
        </g>
      ))}
      <line x1={l} x2={W - r} y1={H - bottom} y2={H - bottom} stroke={AXIS} />
      {wide && quarterTicks(dates).map((d) => (
        <text key={d} x={xDate(d)} y={H - 6} textAnchor="middle" fontSize="11" fill={INK3}>{`${d.slice(2, 4)}.${d.slice(5, 7)}`}</text>
      ))}
      {wide ? labels.map((lb, i) => (
        <g key={measures[i].id}>
          <line x1={lb.px} x2={lb.px} y1={H - bottom} y2={H - bottom + 8 + lb.row * 14} stroke={AXIS} />
          <text x={lb.px} y={H - bottom + 20 + lb.row * 14} textAnchor="middle" fontSize="12" fontWeight="600" fill={INK}>{measures[i].short}</text>
        </g>
      )) : measures.map((m, i) => (
        <text key={m.id} x={x(i)} y={H - bottom + 18} textAnchor="middle" fontSize="11.5" fontWeight="700" fill={INK}>{i + 1}</text>
      ))}
      <path d={path("context")} fill="none" stroke={SERIES_COLOR.context} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <path d={path("alone")} fill="none" stroke={SERIES_COLOR.alone} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      {measures.map((m, i) => (
        <g key={m.id}>
          <circle cx={x(i)} cy={y(m.conditions.context.favor)} r="4" fill="#fff" stroke={SERIES_COLOR.context} strokeWidth="2">
            <title>{`${m.short} ${m.title} · 누적 맥락 ${pct(m.conditions.context.favor)}`}</title>
          </circle>
          <circle cx={x(i)} cy={y(m.conditions.alone.favor)} r="5.5" fill={SERIES_COLOR.alone} stroke="#fff" strokeWidth="2">
            <title>{`${m.short} ${m.title} · 대책만 ${pct(m.conditions.alone.favor)}`}</title>
          </circle>
        </g>
      ))}
      <text x={x(li) + 10} y={ya + 4} fontSize="12.5" fontWeight="700" fill={INK}>{wide ? "대책만 " : ""}{pct(last.conditions.alone.favor)}</text>
      <text x={x(li) + 10} y={yc + 4} fontSize="12.5" fill={INK}>{wide ? "누적 " : ""}{pct(last.conditions.context.favor)}</text>
      {wide && low !== li && (
        <text x={x(low)} y={y(measures[low].conditions.alone.favor) + 22} textAnchor="middle" fontSize="12" fill={INK}>
          최저 {pct(measures[low].conditions.alone.favor)}
        </text>
      )}
    </svg>
  );
}

export default function SeriesLine({ measures }: { measures: SeriesMeasure[] }) {
  return (
    <div className="pp-series-chart">
      <div className="pp-wide-only"><Chart measures={measures} wide /></div>
      <div className="pp-narrow-only"><Chart measures={measures} wide={false} /></div>
    </div>
  );
}

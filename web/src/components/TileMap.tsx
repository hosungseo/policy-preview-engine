import { GAP_BINS, MEAN_BINS, SEQ_BINS, gapBin, meanFill, meanInk, seqBin } from "@/lib/colors";
import { pct, ppoint, signed } from "@/lib/format";
import "./components.css";

// [column, row] on a 5x6 grid, roughly geographic.
const POSITION: Record<string, [number, number]> = {
  서울: [2, 1], 강원: [3, 1], 인천: [1, 2], 경기: [2, 2], 충북: [3, 2], 경북: [4, 2],
  충남: [1, 3], 세종: [2, 3], 대전: [3, 3], 대구: [4, 3], 울산: [5, 3],
  전북: [1, 4], 경남: [4, 4], 부산: [5, 4], 광주: [1, 5], 전남: [2, 5], 제주: [1, 6],
};

export interface Tile { province: string; n: number; mean: number | null }

// mode "mean": average support on -2..+2 (diverging). "share": a probability 0..1 (sequential).
// "gap": a probability coloured by its gap from `base` (e.g. the national value), so small differences still show.
// `compact` is for grids of small maps: no legend of its own (the grid shows one) and the gap without its unit.
export default function TileMap({ tiles, minN = 5, mode = "mean", label = "시도별 평균 지지", base = 0, compact = false, unit = "명" }: {
  tiles: Tile[]; minN?: number; mode?: "mean" | "share" | "gap"; label?: string; base?: number; compact?: boolean; unit?: string;
}) {
  const gapOf = (v: number | null) => (v ?? 0) - base;
  const fill = (v: number | null) => (mode === "gap" ? gapBin(gapOf(v)).color : mode === "share" ? seqBin(v ?? 0).color : meanFill(v));
  const ink = (v: number | null) => (mode === "gap" ? gapBin(gapOf(v)).ink : mode === "share" ? seqBin(v ?? 0).ink : meanInk(v));
  const show = (v: number | null) => (mode === "mean" ? signed(v) : pct(v ?? 0));
  const bins = mode === "gap" ? GAP_BINS : mode === "share" ? SEQ_BINS : MEAN_BINS;
  return (
    <div>
      <div className={`pp-tiles${compact ? " is-compact" : ""}`} role="img" aria-label={label}>
        {tiles.map((t) => {
          const [col, row] = POSITION[t.province] ?? [1, 1];
          const small = t.n < minN;
          return (
            <div key={t.province} className={`pp-tile${small ? " is-small" : ""}`}
              style={{ gridColumn: col, gridRow: row, ...(small ? {} : { background: fill(t.mean), color: ink(t.mean) }) }}>
              <b>{t.province}</b>
              <span>{small ? `${t.n}${unit}` : show(t.mean)}</span>
              {!small && <span>{mode === "gap" ? `${ppoint(gapOf(t.mean))}${compact ? "" : "%p"}` : `${t.n}${unit}`}</span>}
            </div>
          );
        })}
      </div>
      {!compact && <ul className="pp-legend">
        {bins.map((b) => (
          <li key={b.label}><span className="pp-swatch" style={{ background: b.color, border: "1px solid #cdd1d5" }} />{b.label}</li>
        ))}
        <li><span className="pp-swatch" style={{ background: "#fff", border: "1px dashed #cdd1d5" }} />{minN}{unit} 미만(해석 안 함)</li>
      </ul>}
    </div>
  );
}

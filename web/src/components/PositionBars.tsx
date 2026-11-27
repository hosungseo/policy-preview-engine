import { SUPPORT_COLOR, SUPPORT_INK } from "@/lib/colors";
import { pct } from "@/lib/format";
import "./components.css";

const LEVELS: [string, string][] = [["-1", "반대"], ["0", "중립"], ["1", "찬성"]];

// One stacked bar per provision: probability of opposing, staying neutral and supporting it (Jev, panel mean).
export default function PositionBars({ rows }: { rows: { id: string; label: string; oppose: number; support: number }[] }) {
  return (
    <div>
      <div className="pp-dist">
        {rows.map((r) => {
          const shares = [r.oppose, Math.max(0, 1 - r.oppose - r.support), r.support];
          return (
            <div className="pp-dist-row pp-posbar-row" key={r.id}>
              <div className="pp-dist-label">{r.label}</div>
              <div className="pp-dist-bar" role="img"
                aria-label={`${r.label}: ${LEVELS.map(([, name], i) => `${name} ${pct(shares[i])}`).join(", ")}`}>
                {LEVELS.map(([k], i) => shares[i] <= 0.001 ? null : (
                  <div key={k} className="pp-dist-seg" style={{ width: `${shares[i] * 100}%`, background: SUPPORT_COLOR[k], color: SUPPORT_INK[k] }}>
                    {shares[i] >= 0.09 ? pct(shares[i]) : ""}
                  </div>
                ))}
              </div>
              <div className="pp-dist-nums">반대 <b>{pct(r.oppose)}</b> · 중립 <b>{pct(shares[1])}</b> · 찬성 <b>{pct(r.support)}</b></div>
            </div>
          );
        })}
      </div>
      <ul className="pp-legend">
        {LEVELS.map(([k, name]) => <li key={k}><span className="pp-swatch" style={{ background: SUPPORT_COLOR[k] }} />{name}</li>)}
      </ul>
    </div>
  );
}

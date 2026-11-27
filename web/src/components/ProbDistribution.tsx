import { SUPPORT_COLOR, SUPPORT_INK } from "@/lib/colors";
import { SUPPORT_LABEL, pct } from "@/lib/format";
import "./components.css";

const KEYS = ["-2", "-1", "0", "1", "2"];

export interface DistRow { label: string; sub: string; shares: number[]; note?: string }

// Five-level stance shares (strongly oppose ... strongly support) as one stacked bar per row.
export default function ProbDistribution({ rows }: { rows: DistRow[] }) {
  return (
    <div>
      <div className="pp-dist">
        {rows.map((row) => (
          <div className="pp-dist-row" key={row.label}>
            <div className="pp-dist-label">{row.label}<small>{row.sub}</small></div>
            <div className="pp-dist-bar" role="img"
              aria-label={`${row.label}: ${KEYS.map((k, i) => `${SUPPORT_LABEL[k]} ${pct(row.shares[i])}`).join(", ")}`}>
              {KEYS.map((k, i) => {
                const share = row.shares[i] ?? 0;
                if (share <= 0.001) return null;
                return (
                  <div key={k} className="pp-dist-seg" title={`${SUPPORT_LABEL[k]} ${pct(share)}`}
                    style={{ width: `${share * 100}%`, background: SUPPORT_COLOR[k], color: SUPPORT_INK[k] }}>
                    {share >= 0.09 ? pct(share) : ""}
                  </div>
                );
              })}
            </div>
            <div className="pp-dist-nums">
              {KEYS.map((k, i) => (
                <span key={k}>{SUPPORT_LABEL[k]} <b>{pct(row.shares[i] ?? 0)}</b>{k !== "2" ? " · " : ""}</span>
              ))}
              {row.note && <> — {row.note}</>}
            </div>
          </div>
        ))}
      </div>
      <ul className="pp-legend">
        {KEYS.map((k) => (
          <li key={k}><span className="pp-swatch" style={{ background: SUPPORT_COLOR[k] }} />{SUPPORT_LABEL[k]}</li>
        ))}
      </ul>
    </div>
  );
}

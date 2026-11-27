import { SUPPORT_COLOR, SUPPORT_INK } from "@/lib/colors";
import { SUPPORT_LABEL, pct, signed } from "@/lib/format";
import type { Overall } from "@/lib/types";
import "./components.css";

const KEYS = ["-2", "-1", "0", "1", "2"];

export default function SupportDistribution({ rows }: { rows: { label: string; sub: string; overall: Overall }[] }) {
  return (
    <div>
      <div className="pp-dist">
        {rows.map((row) => {
          const n = row.overall.n || 1;
          return (
            <div className="pp-dist-row" key={row.label}>
              <div className="pp-dist-label">{row.label}<small>{row.sub}</small></div>
              <div className="pp-dist-bar" role="img"
                aria-label={`${row.label}: ${KEYS.map((k) => `${SUPPORT_LABEL[k]} ${row.overall.dist[k] ?? 0}명`).join(", ")}`}>
                {KEYS.map((k) => {
                  const count = row.overall.dist[k] ?? 0;
                  if (!count) return null;
                  const share = count / n;
                  return (
                    <div key={k} className="pp-dist-seg" title={`${SUPPORT_LABEL[k]} ${count}명 (${pct(share)})`}
                      style={{ width: `${share * 100}%`, background: SUPPORT_COLOR[k], color: SUPPORT_INK[k] }}>
                      {share >= 0.09 ? pct(share) : ""}
                    </div>
                  );
                })}
              </div>
              <div className="pp-dist-nums">
                {KEYS.map((k) => (
                  <span key={k}>{SUPPORT_LABEL[k]} <b>{row.overall.dist[k] ?? 0}</b>{k !== "2" ? " · " : ""}</span>
                ))}
                {" "}— 평균 <b>{signed(row.overall.mean)}</b>
                {row.overall.ci95 && <> (95% 구간 {signed(row.overall.ci95[0])} ~ {signed(row.overall.ci95[1])})</>}
              </div>
            </div>
          );
        })}
      </div>
      <ul className="pp-legend">
        {KEYS.map((k) => (
          <li key={k}><span className="pp-swatch" style={{ background: SUPPORT_COLOR[k] }} />{SUPPORT_LABEL[k]}</li>
        ))}
      </ul>
    </div>
  );
}

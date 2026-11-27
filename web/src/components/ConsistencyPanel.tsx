import { signed } from "@/lib/format";
import type { Consistency, Reaction } from "@/lib/types";
import StatTile from "./StatTile";
import SupportBadge from "./SupportBadge";
import "./components.css";

// Jev read each LLM reason without its label; answers whose own support disagrees by the threshold are listed.
export default function ConsistencyPanel({ consistency, reactions }: { consistency: Consistency; reactions: Map<string, Reaction> }) {
  const c = consistency;
  return (
    <div>
      <div className="pp-grid-4">
        <StatTile label="읽은 응답" value={`${c.n.toLocaleString()}건`} note="LLM 패널 전체" />
        <StatTile label="어긋난 응답" value={`${c.flagged.toLocaleString()}건`} note={`${c.threshold}단계 이상 차이`} />
        <StatTile label="상관계수" value={c.corr === null ? "–" : c.corr.toFixed(2)} note="LLM 찬반과 Jev 판독" />
        <StatTile label="평균 차이" value={c.mean_abs_diff === null ? "–" : c.mean_abs_diff.toFixed(2)} note="5단계 척도 기준" />
      </div>
      {c.items.length > 0 && (
        <div className="pp-card" style={{ marginTop: 12 }}>
          <h3 className="pp-h3">어긋난 응답{c.flagged > c.items.length ? ` (상위 ${c.items.length}건)` : ""}</h3>
          <ul className="pp-cons-list">
            {c.items.map((it) => {
              const r = reactions.get(it.rid);
              if (!r) return null;
              return (
                <li key={it.rid}>
                  <p>“{r.reason}”</p>
                  <span>인물이 붙인 찬반 <SupportBadge value={r.support} /> · Jev 판독 <b>{signed(it.jev)}</b></span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

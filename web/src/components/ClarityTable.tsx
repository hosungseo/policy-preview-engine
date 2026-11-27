import { SEQ_BINS, seqBin } from "@/lib/colors";
import { pct } from "@/lib/format";
import type { Clarity } from "@/lib/types";
import "./components.css";

// Provisions (rows) x plain-language problems (columns): the probability Jev gives that the problem exists.
export default function ClarityTable({ clarity, segments }: { clarity: Clarity; segments: { id: string; label: string }[] }) {
  const byId = new Map(clarity.clauses.map((c) => [c.segment_id, c]));
  return (
    <div className="pp-card pp-heat">
      <div className="pp-heat-wrap">
        <table className="pp-heat-table pp-clarity-table">
          <thead>
            <tr>
              <th scope="col">조항</th>
              {clarity.indicators.map((i) => <th key={i.key} scope="col">{i.label}</th>)}
              <th scope="col">걸린 지표</th>
            </tr>
          </thead>
          <tbody>
            {segments.map((s) => {
              const c = byId.get(s.id);
              if (!c) return null;
              return (
                <tr key={s.id}>
                  <th scope="row">{s.label}</th>
                  {clarity.indicators.map((i) => {
                    const v = c.values[i.key] ?? 0;
                    const bin = seqBin(v);
                    return <td key={i.key} style={{ background: bin.color, color: bin.ink }}>{pct(v)}</td>;
                  })}
                  <td className="pp-clarity-count">{c.flags.length}개</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <ul className="pp-legend">
        {SEQ_BINS.map((b) => <li key={b.label}><span className="pp-swatch" style={{ background: b.color }} />{b.label}</li>)}
      </ul>
      <p className="pp-sub" style={{ margin: "4px 0 0" }}>
        칸의 숫자는 그 문제가 있다고 Jev가 본 확률입니다. {pct(clarity.threshold)} 이상이면 ‘걸린 지표’로 셉니다.
      </p>
    </div>
  );
}

export function NoticeChecklist({ clarity }: { clarity: Clarity }) {
  return (
    <div className="pp-card">
      <h3 className="pp-h3">안내문에 있어야 할 것</h3>
      <ul className="pp-checklist">
        {clarity.document.map((d) => {
          const ok = d.p >= clarity.threshold;
          return (
            <li key={d.key}>
              <span className={`pp-check-chip${ok ? " is-ok" : ""}`}>{ok ? "있음" : "빠진 듯"}</span>
              <span>{d.label}</span>
              <b>{pct(d.p)}</b>
            </li>
          );
        })}
      </ul>
      <p className="pp-sub" style={{ margin: "8px 0 0" }}>
        숫자는 본문에 그 안내가 있다고 Jev가 본 확률입니다. 이 도구에 넣은 본문만 보므로, 원래 공고의 붙임이나 별도 안내는 반영하지 않습니다.
      </p>
    </div>
  );
}
